import base64
import io
import json
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

import httpx
import win32crypt

from jack_client import API, CLERK, JackClient, JackHTTPError, docx_text
from jack import accept_suggestion, decide_suggestion, export_cv, simulation_receipt

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
                export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, root)
            self.assertFalse(list(root.iterdir()))
            client = Fake()
            with self.assertRaises(ValueError):
                export_cv(client, JOB, {'job_match_id': str(uuid.uuid4()), 'review_id': 'review'}, root)
            receipt = export_cv(client, JOB, {'job_match_id': JOB, 'review_id': 'review'}, root)
            self.assertEqual(Path(receipt['path']).read_bytes(), docx())
            self.assertEqual(receipt['text'], 'Robotics intern')

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
