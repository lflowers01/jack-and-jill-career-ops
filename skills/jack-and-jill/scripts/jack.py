"""Request-only Jack CV workflow. Run with --help; never rewrites a CV locally."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import subprocess
from pathlib import Path

from jack_client import JackClient, JackHTTPError, docx_text, identifier

ROOT = Path(os.environ.get('CAREER_OPS_REPO', Path.cwd())).resolve()


def data_root():
    if not (ROOT / 'path-resolver.mjs').is_file():
        raise ValueError('Run from the Career Ops repository or set CAREER_OPS_REPO to it.')
    code = "import { getCareerOpsRoot } from './path-resolver.mjs'; console.log(getCareerOpsRoot())"
    return Path(subprocess.check_output(['node', '--input-type=module', '-e', code], cwd=ROOT, text=True).strip())


def simulation_receipt(events, job_match_id, source_version_id):
    calls = {e.get('toolCallId'): e for e in events if e.get('type') == 'tool-input-available'
             and e.get('toolName') == 'run_application_simulation'}
    for event in events:
        call = calls.get(event.get('toolCallId'))
        output = event.get('output', {})
        if call and event.get('type') == 'tool-output-available' and output.get('status') == 'success':
            args = call.get('input', {})
            if args.get('job_match_id') == job_match_id and args.get('cv_document_version_id') == source_version_id:
                return {'job_match_id': job_match_id, 'source_version_id': source_version_id,
                        'review_id': output['review_id'], 'cv_version_id': output['cv_document_version_id'],
                        'analysed_seconds': output.get('analysed_seconds')}
    return None


def review_meta(data):
    return {k: data.get(k) for k in ('id', 'source_user_info_id', 'parent_version_id', 'job_match_id',
                                     'origin', 'status', 'failure_reason', 'missing_facts',
                                     'ai_telltale_signs', 'threads', 'filename', 'created_at')}


def current_thread(version, thread_id, snapshot=None):
    """Decisions clone thread IDs; remap only an unchanged, uniquely reviewed edit."""
    thread = next((t for t in version.get('threads', []) if t['id'] == identifier(thread_id)), None)
    keys = ('kind', 'title', 'before', 'after', 'fix_id', 'review_id')
    if snapshot is not None:
        matches = [t for t in version.get('threads', []) if all(t.get(k) == snapshot.get(k) for k in keys)]
        if len(matches) != 1 or (thread and thread is not matches[0]):
            raise ValueError('The reviewed edit changed or is ambiguous. Read the current CV and review again.')
        thread = matches[0]
    return thread


def decide_suggestion(client, job_match_id, thread_id, expected_after, *, accept=True,
                      snapshot=None, source_id=None):
    version = client.cv(job_match_id=job_match_id, source_id=source_id)
    thread = current_thread(version, thread_id, snapshot)
    # Empty after is a valid deletion; null/missing after is not an edit.
    if not thread or thread.get('kind') != 'suggestion' or not isinstance(thread.get('after'), str):
        raise ValueError('This is not a proposed edit on the current role CV. Ask Jack to turn its note into an edit first.')
    if thread['after'] != expected_after:
        raise ValueError('Jack changed the recommendation. Read and fact-check the current edit before accepting it.')
    decision = 'accepted' if accept else 'rejected'
    if thread.get('status') == decision:
        return {'already_' + decision: True, 'version': review_meta(version)}
    if thread.get('status') not in (('open',) if accept else ('open', 'orphaned')):
        raise ValueError('The recommendation is not open; inspect its current status')
    reviewed = dict(thread)
    try:
        client.request('POST', f'/candidate/cv-document/thread/{identifier(thread["id"])}/decide',
                       json={'accept': accept, 'content_base64': None})
    except JackHTTPError as exc:
        if exc.status_code != 409:
            raise
        fresh = client.cv(job_match_id=job_match_id, source_id=source_id)
        latest = current_thread(fresh, thread['id'], reviewed)
        if latest and latest.get('status') == decision:
            return {'reconciled_after_conflict': True, 'version': review_meta(fresh)}
        # A proposed DOCX view can already contain after-text before acceptance.
        # Text equality never authorizes marking a conflicting decision complete.
        raise ValueError('Jack reported an edit conflict. Current state refreshed; no write retried. '
                         f'CV {fresh["id"]}; thread {latest["id"] if latest else "missing"}. '
                         'Review pending edits or use the website editor for this unsupported case.') from exc
    fresh = client.cv(job_match_id=job_match_id, source_id=source_id)
    latest = current_thread(fresh, thread['id'], reviewed)
    if not latest or latest.get('status') != decision:
        raise ValueError('Jack did not confirm the decision in the current CV. No write was retried.')
    return review_meta(fresh)


def accept_suggestion(client, job_match_id, thread_id, expected_after, **kwargs):
    return decide_suggestion(client, job_match_id, thread_id, expected_after, **kwargs)


def export_cv(client, job_match_id, simulation, output_root=None):
    job_match_id = identifier(job_match_id)
    version = client.cv(job_match_id=job_match_id)
    if simulation.get('job_match_id') != job_match_id or not simulation.get('review_id'):
        raise ValueError('Final download requires a successful simulator receipt for this exact job')
    if simulation['review_id'] not in {t.get('review_id') for t in version.get('threads', [])}:
        raise ValueError('The current CV does not carry the simulator review in the supplied receipt')
    if version.get('status') != 'ready':
        raise ValueError('Jack has not finished this CV')
    pending = [t['id'] for t in version.get('threads', []) if t.get('status') in ('open', 'orphaned')]
    if pending:
        raise ValueError(f'{len(pending)} Jack recommendations still need work. Complete them before final export.')
    data = client.content(version['id'])
    output_root = output_root or data_root() / 'output' / 'jack-and-jill'
    target = output_root / job_match_id / (identifier(version['id']) + '.docx')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError('An existing download differs; preserve it and investigate the version')
    else:
        with target.open('xb') as stream:
            stream.write(data)
    receipt = {'path': str(target), 'sha256': hashlib.sha256(data).hexdigest(), 'version_id': version['id'],
               'job_match_id': job_match_id, 'simulation': simulation, 'bytes': len(data), 'text': docx_text(data),
               'source': 'Jack website CV content API'}
    target.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['documents', 'job', 'cv', 'simulate', 'refine', 'accept', 'reject', 'resolve-note', 'download', 'chat-status'])
    parser.add_argument('--job', help='Exact Jack job_match_id')
    parser.add_argument('--source', help='Master CV user_info_id (cv, accept, reject)')
    parser.add_argument('--version', help='Exact source CV version to simulate')
    parser.add_argument('--thread', help='Right-panel suggestion/note ID')
    parser.add_argument('--input', help='UTF-8 verified facts / Jack recommendation JSON file; accept requires {"after": "exact reviewed text"}')
    parser.add_argument('--message-id', help='Stable UUID for one Jack chat request; retain it if delivery is uncertain')
    parser.add_argument('--result', help='Local JSON result file for inspection; required for simulation/refinement')
    parser.add_argument('--simulation', help='Successful simulator result JSON; mandatory for final download')
    args = parser.parse_args()
    client = JackClient()
    if args.command == 'documents':
        data = client.request('GET', '/candidate/documents')
        result = {'documents': [{k: d.get(k) for k in ('id', 'filename', 'type', 'is_active', 'created_for', 'edited_copy')}
                                for d in data['documents']], 'role_cvs': data.get('detached_cvs', [])}
    elif args.command == 'job':
        result = client.request('GET', f'/candidate/job/match/{identifier(args.job)}')
    elif args.command == 'cv':
        data = client.cv(source_id=args.source, job_match_id=args.job)
        result = review_meta(data)
        if data.get('status') == 'ready':
            result['text'] = docx_text(client.content(data['id']))
            result['text_view'] = 'Proposed final DOCX view; open tracked edits can appear here before acceptance. Verify thread status.'
    elif args.command == 'chat-status':
        result = client.request('POST', '/jack-chat/connect', json={'onboarding_call': False, 'page_context': None})
    elif args.command in ('simulate', 'refine'):
        if not args.message_id or not args.result:
            parser.error('Simulation/refinement requires --message-id UUID and --result PATH so the turn can be audited without sending it twice')
        identifier(args.message_id)
        output = Path(args.result).resolve()
        if output.exists():
            raise ValueError('Result file already exists. Inspect it rather than starting another Jack turn.')
        role = client.request('GET', f'/candidate/job/match/{identifier(args.job)}')
        guard = ('Preparation only. Never submit, request intros, message employers, change visibility/search/profile, '
                 'or mark a role Applied. Do not invent facts. All tailoring must happen in Jack, not locally. ')
        if args.command == 'simulate':
            identifier(args.version)
            message = (f'Run the Application simulator now for job_match_id={role["id"]} '
                       f'({role["position"]} at {role["company"]}) and cv_document_version_id={args.version}. '
                       'Read handbooks/application_simulator.md, then call run_application_simulation with that exact role and CV. '
                       'Run it; do not merely display the configuration card. ' + guard)
        else:
            thread_id = identifier(args.thread)
            current = client.cv(job_match_id=args.job)
            if not any(t['id'] == thread_id for t in current.get('threads', [])):
                raise ValueError('The note does not belong to this role CV')
            if not args.input:
                parser.error('Refinement requires --input with source-backed facts and requested correction')
            facts = Path(args.input).read_text(encoding='utf-8')
            message = (f'For the role CV job_match_id={role["id"]}, version_id={current["id"]}, '
                       f'work on right-panel note thread_id={thread_id}. Read the current CV and note. '
                       'Produce a proposed edit in Jack addressing the whole recommendation, grounded in the verified context below. '
                       'Do not mark it done without an actual supported edit. ' + guard + '\nVerified context:\n' + facts)
        output.parent.mkdir(parents=True, exist_ok=True)
        # A sent marker is deliberately retained on timeout: a missing result is not permission to resend.
        marker = output.with_suffix(output.suffix + '.sent.json')
        with marker.open('x', encoding='utf-8') as f:
            json.dump({'message_id': args.message_id, 'job_match_id': args.job,
                       'source_version_id': args.version, 'command': args.command}, f)
        result = client.chat(message, args.message_id)
        if args.command == 'simulate':
            result['simulation'] = simulation_receipt(result['events'], args.job, args.version)
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'result': str(output), 'message_id': args.message_id, 'events': len(result['events']),
                          'complete': result['complete'], 'simulation': result.get('simulation')}))
        return
    elif args.command in ('accept', 'reject'):
        if not args.input:
            parser.error('Acceptance requires --input JSON with the exact fact-checked after text')
        reviewed = json.loads(Path(args.input).read_text(encoding='utf-8'))
        snapshot = reviewed.get('thread')
        after = reviewed['after'] if 'after' in reviewed else snapshot['after']
        result = decide_suggestion(client, args.job, args.thread, after, accept=args.command == 'accept',
                                   snapshot=snapshot, source_id=args.source)
    elif args.command == 'resolve-note':
        current = client.cv(job_match_id=args.job)
        thread = next((t for t in current.get('threads', []) if t['id'] == identifier(args.thread)), None)
        if not thread or thread.get('kind') != 'comment' or thread.get('after'):
            raise ValueError('This command resolves a reviewed comment only, never an actual edit')
        reason = json.loads(Path(args.input).read_text(encoding='utf-8'))['reason']
        if not isinstance(reason, str) or len(reason.strip()) < 30:
            raise ValueError('Record how the comment was handled, with its factual source or the remaining unknown')
        if thread.get('status') not in ('open', 'orphaned'):
            result = {'already_resolved': True}
        else:
            client.request('POST', f'/candidate/cv-document/thread/{identifier(args.thread)}/reply', json={'text': reason})
            result = review_meta(client.request('POST', f'/candidate/cv-document/thread/{identifier(args.thread)}/decide',
                                                json={'accept': True, 'content_base64': None}))
    else:
        if not args.simulation:
            parser.error('Final download requires --simulation with the exact-job simulator result')
        simulation = json.loads(Path(args.simulation).read_text(encoding='utf-8')).get('simulation') or {}
        result = export_cv(client, args.job, simulation)
    if args.result:
        Path(args.result).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'result': str(Path(args.result).resolve())}))
    else:
        print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)
