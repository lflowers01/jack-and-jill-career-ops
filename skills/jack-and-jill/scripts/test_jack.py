import base64
import io
import json
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch
from pathlib import Path

import httpx
import win32crypt

from jack_client import API, CLERK, JackClient, JackHTTPError, docx_text
from jack import accept_suggestion, decide_suggestion, export_cv, simulation_receipt, resolve_note, check_resume_policy, run_chat, main

JOB = str(uuid.uuid4())
VERSION = str(uuid.uuid4())
THREAD = str(uuid.uuid4())


def docx():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Robotics</w:t><w:tab/></w:r><w:del><w:r><w:delText>invented</w:delText></w:r></w:del><w:ins><w:r><w:t>intern</w:t></w:r></w:ins></w:p></w:body></w:document>')
    return out.getvalue()


class Fake:
    def __init__(self, pending=False):
        self.version = {'id': VERSION, 'job_match_id': JOB, 'status': 'ready', 'threads': [
            {'id': THREAD, 'review_id': 'review', 'kind': 'suggestion', 'after': 'Robotics intern',
             'status': 'open' if pending else 'accepted'}]}
        self.writes = []

    def cv(self, **kwargs):
        return self.version

    def content(self, version):
        return docx()

    def request(self, method, path, **kwargs):
        self.writes.append((method, path, kwargs))
        self.version['threads'][0]['status'] = 'accepted' if kwargs['json']['accept'] else 'rejected'
        return self.version


class Tests(unittest.TestCase):
    def test_empty_after_is_a_deletion_and_null_is_not(self):
        client = Fake(True)
        client.version['threads'][0].update(before='Remove this old entry', after='')
        accept_suggestion(client, JOB, THREAD, '')
        self.assertEqual(client.version['threads'][0]['status'], 'accepted')
        self.assertEqual(len(client.writes), 1)
        client = Fake(True)
        client.version['threads'][0]['after'] = None
        with self.assertRaises(ValueError):
            accept_suggestion(client, JOB, THREAD, '')
        self.assertFalse(client.writes)

    def test_rejection_of_pending_or_orphaned_bad_edit_is_explicit_and_idempotent(self):
        client = Fake(True)
        client.version['threads'][0]['status'] = 'orphaned'
        decide_suggestion(client, JOB, THREAD, 'Robotics intern', accept=False)
        self.assertFalse(client.writes[0][2]['json']['accept'])
        decide_suggestion(client, JOB, THREAD, 'Robotics intern', accept=False)
        self.assertEqual(len(client.writes), 1)

    def test_cloned_thread_ids_require_an_unchanged_unique_snapshot(self):
        client = Fake(True)
        reviewed = dict(client.version['threads'][0])
        new_id = str(uuid.uuid4())
        client.version['threads'][0]['id'] = new_id
        with self.assertRaises(ValueError):
            accept_suggestion(client, JOB, THREAD, 'Robotics intern')
        accept_suggestion(client, JOB, THREAD, 'Robotics intern', snapshot=reviewed)
        self.assertIn(new_id, client.writes[0][1])
        client = Fake(True)
        client.version['threads'].append(dict(client.version['threads'][0], id=new_id))
        with self.assertRaises(ValueError):
            accept_suggestion(client, JOB, THREAD, 'Robotics intern', snapshot=reviewed)
        self.assertFalse(client.writes)

    def test_conflict_is_read_back_not_retried_or_accepted_from_proposed_text(self):
        class Conflict(Fake):
            def request(self, method, path, **kwargs):
                self.writes.append((method, path, kwargs))
                raise JackHTTPError(409, method, path)
        client = Conflict(True)
        with self.assertRaisesRegex(ValueError, 'no write retried'):
            accept_suggestion(client, JOB, THREAD, 'Robotics intern')
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.version['threads'][0]['status'], 'open')

    def test_conflict_after_committed_decision_is_reconciled_without_resend(self):
        class Committed(Fake):
            def request(self, method, path, **kwargs):
                super().request(method, path, **kwargs)
                raise JackHTTPError(409, method, path)
        client = Committed(True)
        result = accept_suggestion(client, JOB, THREAD, 'Robotics intern')
        self.assertTrue(result['reconciled_after_conflict'])
        self.assertEqual(len(client.writes), 1)

    def test_visible_docx_uses_insertions_not_deleted_text(self):
        self.assertEqual(docx_text(docx()), 'Robotics intern')

    def test_accept_requires_exact_current_reviewed_edit(self):
        client = Fake(True)
        with self.assertRaises(ValueError):
            accept_suggestion(client, JOB, THREAD, 'Invented expertise')
        self.assertFalse(client.writes)
        accept_suggestion(client, JOB, THREAD, 'Robotics intern')
        self.assertEqual(len(client.writes), 1)
        accept_suggestion(client, JOB, THREAD, 'Robotics intern')
        self.assertEqual(len(client.writes), 1)

    def test_export_requires_matching_simulation_and_no_pending_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = Fake(True)
            with self.assertRaises(ValueError):
                export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, root, policy={})
            self.assertFalse(list(root.iterdir()))
            client = Fake()
            with self.assertRaises(ValueError):
                export_cv(client, JOB, {'job_match_id': str(uuid.uuid4()), 'review_id': 'review'}, root, policy={})
            receipt = export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, root, policy={})
            self.assertEqual(Path(receipt['path']).read_bytes(), docx())
            self.assertEqual(receipt['text'], 'Robotics intern')

    def test_resume_policy_blocks_status_variants_but_preserves_fundraising(self):
        policy = {'forbid_work_authorization': True}
        for text in ['Authorized to work in the US', 'U.S. work-authorized', 'Work\n authorization: eligible',
                     'No sponsorship required', 'Does not require sponsorship', 'Visa sponsorship: not needed',
                     'Sponsorship is not required', 'US citizen', 'Permanent resident', 'Work‑authorized',
                     'Eligible to work in the US', 'Work eligibility: unrestricted', 'Visa status: F1',
                     'F-1 visa', 'Requires sponsorship', 'Sponsorship: none']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_resume_policy(text, policy)
        check_resume_policy('Raised funds through grants and sponsorships for a robotics team.', policy)
        check_resume_policy('Robotics student', policy)
        with self.assertRaises(ValueError):
            check_resume_policy('An UNVERIFIED\nGPA placeholder', {'forbidden_phrases': ['unverified GPA']})
        for invalid in ([], {'forbid_work_authorization': 'false'}, {'forbidden_phrases': [None]}):
            with self.assertRaises(ValueError):
                check_resume_policy('Robotics student', invalid)

    def test_export_blocks_unknown_or_missing_thread_status(self):
        for status in (None, 'processing', 'future_api_status'):
            client = Fake()
            client.version['threads'][0]['status'] = status
            with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'unknown status'):
                export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, Path(directory), policy={})

    def test_policy_is_loaded_from_data_root_and_checked_before_any_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config' / 'jack-and-jill.json').write_text(json.dumps({'forbidden_phrases': ['Robotics intern']}))
            with patch('jack.data_root', return_value=root), self.assertRaisesRegex(ValueError, 'forbidden'):
                export_cv(Fake(), JOB, {'job_match_id': JOB, 'review_id': 'review'}, root / 'final')
            self.assertFalse((root / 'final').exists())

    def test_resolve_note_confirms_reply_cloned_ids_and_terminal_status_without_duplicates(self):
        class Comments(Fake):
            def request(self, method, path, **kwargs):
                self.writes.append((method, path, kwargs))
                t = self.version['threads'][0]
                if path.endswith('/reply'):
                    t.setdefault('replies', []).append({'author': 'candidate', 'text': kwargs['json']['text']})
                else:
                    t['status'] = 'resolved'
                t['id'] = str(uuid.uuid4())
                return self.version
        client = Comments(True)
        t = client.version['threads'][0]
        t.update(kind='comment', after=None, title='Unknown GPA')
        reviewed = {'thread': dict(t), 'reason': 'Source: confirmed profile has no Purdue GPA; keep the GPA omitted.'}
        with tempfile.TemporaryDirectory() as directory:
            op = Path(directory) / 'resolution.json'
            result = resolve_note(client, JOB, THREAD, reviewed, op)
            self.assertEqual(result['threads'][0]['status'], 'resolved')
            resolve_note(client, JOB, THREAD, reviewed, op)
            self.assertEqual(len(client.writes), 2)

    def test_note_uncertain_reply_is_never_resent_and_rejected_is_not_resolved(self):
        class NoReply(Fake):
            def request(self, method, path, **kwargs):
                self.writes.append((method, path, kwargs))
                raise httpx.ReadTimeout('delivery uncertain')
        client = NoReply(True)
        client.version['threads'][0].update(kind='comment', after=None)
        reviewed = {'reason': 'Source: candidate has no confirmed PLC experience, so no PLC claim was added.'}
        with tempfile.TemporaryDirectory() as directory:
            op = Path(directory) / 'resolution.json'
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'No .*retried|No reply resent'):
                    resolve_note(client, JOB, THREAD, reviewed, op)
            self.assertEqual(len(client.writes), 1)
            client.version['threads'][0]['status'] = 'rejected'
            with self.assertRaisesRegex(ValueError, 'terminal status'):
                resolve_note(client, JOB, THREAD, reviewed, op)

    def test_note_committed_conflict_reconciles_but_unconfirmed_decision_never_resends(self):
        class Conflict(Fake):
            committed = False
            def request(self, method, path, **kwargs):
                self.writes.append((method, path, kwargs))
                t = self.version['threads'][0]
                if path.endswith('/reply'):
                    t.setdefault('replies', []).append({'author': 'candidate', 'text': kwargs['json']['text']})
                    return self.version
                if self.committed:
                    t['status'] = 'resolved'
                raise JackHTTPError(409, method, path)
        for committed in (False, True):
            client = Conflict(True)
            client.committed = committed
            client.version['threads'][0].update(kind='comment', after=None)
            reviewed = {'reason': 'Source: no verified GPA is available; omit the proposed GPA field entirely.'}
            with tempfile.TemporaryDirectory() as directory:
                op = Path(directory) / 'resolution.json'
                if committed:
                    self.assertTrue(resolve_note(client, JOB, THREAD, reviewed, op)['reconciled_after_conflict'])
                else:
                    for _ in range(2):
                        with self.assertRaises(ValueError):
                            resolve_note(client, JOB, THREAD, reviewed, op)
                self.assertEqual(len(client.writes), 2)

    def test_export_accepts_resolved_comments_but_not_accepted_or_unknown_comments(self):
        for status in ('resolved', 'accepted', 'rejected', None):
            client = Fake()
            client.version['threads'].append({'id': str(uuid.uuid4()), 'kind': 'comment', 'status': status})
            with tempfile.TemporaryDirectory() as directory:
                if status == 'resolved':
                    export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, Path(directory), policy={})
                else:
                    with self.assertRaisesRegex(ValueError, 'unknown status'):
                        export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, Path(directory), policy={})

    def test_interrupted_chat_preserves_events_and_blocks_duplicate_run(self):
        class Interrupted:
            calls = 0
            def chat(self, message, message_id, on_event):
                self.calls += 1
                on_event({'type': 'text-delta', 'delta': 'Saved partial result'})
                raise httpx.ReadTimeout('interrupted')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run.json'
            client = Interrupted()
            meta = {'command': 'refine', 'job_match_id': JOB, 'source_version_id': VERSION}
            with self.assertRaises(httpx.ReadTimeout):
                run_chat(client, 'Refine', str(uuid.uuid4()), output, meta)
            saved = json.loads(output.read_text())
            self.assertEqual(saved['events'][0]['delta'], 'Saved partial result')
            self.assertFalse(saved['complete'])
            with self.assertRaises(ValueError):
                run_chat(client, 'Refine', str(uuid.uuid4()), output, meta)
            self.assertEqual(client.calls, 1)

    def test_incomplete_chat_is_not_success_and_does_not_need_shell_handle_for_status(self):
        class Incomplete:
            def chat(self, message, message_id, on_event):
                return {'complete': False, 'events': [], 'message_id': message_id}
            def request(self, *args, **kwargs):
                return {'turn_in_progress': False}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run.json'
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                run_chat(Incomplete(), 'Refine', str(uuid.uuid4()), output, {'command': 'refine'})
            original = output.read_bytes()
            with patch('jack.JackClient', return_value=Incomplete()), patch('sys.argv', ['jack.py', 'run-status', '--result', str(output)]), patch('sys.stdout', new_callable=io.StringIO) as out:
                main()
            status = json.loads(out.getvalue())
            self.assertEqual(status['jack_turn_in_progress'], False)
            self.assertEqual(status['complete'], False)
            self.assertEqual(output.read_bytes(), original)

    def test_grouped_source_refinement_uses_guarded_cli_and_durable_result(self):
        class Source(Fake):
            def cv(self, **kwargs):
                self.args = kwargs
                return self.version
            def chat(self, message, message_id, on_event):
                self.message = message
                on_event({'type': 'finish'})
                return {'message_id': message_id, 'complete': True, 'events': [{'type': 'finish'}]}
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory) / 'facts.txt'
            context.write_text('Confirmed title and project identity only.')
            output = Path(directory) / 'refined.json'
            source_id = str(uuid.uuid4())
            client = Source()
            with patch('jack.JackClient', return_value=client), patch('sys.argv', ['jack.py', 'refine', '--source', source_id, '--input', str(context), '--message-id', str(uuid.uuid4()), '--result', str(output)]), patch('sys.stdout', new_callable=io.StringIO):
                main()
            self.assertEqual(client.args['source_id'], source_id)
            self.assertIn('all pending right-panel recommendations', client.message)
            self.assertIn('Never submit', client.message)
            self.assertIn(context.read_text(), client.message)
            self.assertTrue(json.loads(output.read_text())['complete'])

    def test_simulation_finish_without_matching_receipt_is_not_success(self):
        class NoSimulation:
            def chat(self, message, message_id, on_event):
                on_event({'type': 'finish'})
                return {'complete': True, 'events': [{'type': 'finish'}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run.json'
            with self.assertRaisesRegex(ValueError, 'simulator receipt'):
                run_chat(NoSimulation(), 'Simulate', str(uuid.uuid4()), output,
                         {'command': 'simulate', 'job_match_id': JOB, 'source_version_id': VERSION})
            self.assertIsNone(json.loads(output.read_text())['simulation'])

    def test_real_sse_disconnect_preserves_received_event_without_resend(self):
        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"type":"text-delta","delta":"Checkpointed"}\n\n'
                raise httpx.ReadTimeout('stream disconnected')
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path.endswith('/connect'):
                return httpx.Response(200, json={'turn_in_progress': False})
            return httpx.Response(200, stream=BrokenStream())
        client = JackClient(httpx.Client(transport=httpx.MockTransport(handler)))
        client._token = lambda: 'test-token'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run.json'
            with self.assertRaises(httpx.ReadTimeout):
                run_chat(client, 'Refine', str(uuid.uuid4()), output, {'command': 'refine'})
            saved = json.loads(output.read_text())
            self.assertEqual(saved['events'], [{'type': 'text-delta', 'delta': 'Checkpointed'}])
            self.assertFalse(saved['complete'])
            self.assertEqual(sum(p.endswith('/messages/stream') for p in calls), 1)

    def test_decision_transport_timeout_is_read_back_once_without_resend(self):
        class Timeout(Fake):
            def request(self, method, path, **kwargs):
                super().request(method, path, **kwargs)
                raise httpx.ReadTimeout('response lost after commit')
        client = Timeout(True)
        self.assertTrue(accept_suggestion(client, JOB, THREAD, 'Robotics intern')['reconciled_after_conflict'])
        self.assertEqual(len(client.writes), 1)

    def test_simulation_requires_actual_success_for_exact_job_and_source(self):
        events = [{'type': 'tool-input-available', 'toolCallId': 'call', 'toolName': 'run_application_simulation',
                   'input': {'job_match_id': JOB, 'cv_document_version_id': VERSION}},
                  {'type': 'tool-output-available', 'toolCallId': 'call', 'output':
                   {'status': 'success', 'review_id': 'review', 'cv_document_version_id': VERSION}}]
        self.assertIsNotNone(simulation_receipt(events, JOB, VERSION))
        self.assertIsNone(simulation_receipt(events, str(uuid.uuid4()), VERSION))
        self.assertIsNone(simulation_receipt([{'type': 'finish'}], JOB, VERSION))

    def test_encrypted_session_refresh_and_token_host_boundary(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.host == 'clerk.jackandjill.ai':
                self.assertEqual(request.headers['Authorization'], 'client-secret')
                return httpx.Response(200, json={'jwt': 'session-secret'})
            self.assertEqual(request.url.host, 'api.jackandjill.ai')
            self.assertEqual(request.headers['Authorization'], 'Bearer session-secret')
            return httpx.Response(200, json={'ok': True})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.dpapi'
            path.write_bytes(win32crypt.CryptProtectData(json.dumps({'sessionId': 'sess_test', 'auth': 'client-secret'}).encode(), 'test', None, None, None, 0))
            self.assertNotIn(b'client-secret', path.read_bytes())
            client = JackClient(httpx.Client(transport=httpx.MockTransport(handler)), path)
            self.assertTrue(client.request('GET', '/candidate/info')['ok'])
            self.assertTrue(client.request('GET', '/candidate/documents')['ok'])
            self.assertEqual(len(calls), 3)
            for path in ['https://attacker.test', '//attacker.test', '/candidate/../admin', '/user/account']:
                with self.assertRaises(ValueError):
                    client.request('GET', path)

    def test_chat_requires_finish_and_does_not_resend_partial_stream(self):
        for finished in (False, True):
            calls = []
            def handler(request):
                calls.append(request)
                if request.url.path.endswith('/connect'):
                    return httpx.Response(200, json={'turn_in_progress': False})
                body = 'data: {"type":"text-delta","delta":"Partial"}\n\n'
                if finished:
                    body += 'data: {"type":"finish"}\n\ndata: [DONE]\n\n'
                return httpx.Response(200, text=body, headers={'Content-Type': 'text/event-stream'})
            client = JackClient(httpx.Client(transport=httpx.MockTransport(handler)))
            client._token = lambda: 'test-token'
            result = client.chat('Run exact job simulator', str(uuid.uuid4()))
            self.assertEqual(result['complete'], finished)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result['events'][0]['delta'], 'Partial')

    def test_expired_session_is_not_retried_or_reported_as_empty(self):
        def handler(request):
            return httpx.Response(401, json={'secret': 'must not appear in errors'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.dpapi'
            path.write_bytes(win32crypt.CryptProtectData(json.dumps({'sessionId': 'sess_test', 'auth': 'secret'}).encode(), 'test', None, None, None, 0))
            client = JackClient(httpx.Client(transport=httpx.MockTransport(handler)), path)
            with self.assertRaisesRegex(RuntimeError, 'renewal') as error:
                client.request('GET', '/candidate/info')
            self.assertNotIn('must not appear', str(error.exception))


if __name__ == '__main__':
    unittest.main()
