"""Jack website requests. Credentials stay in the current Windows user's DPAPI store."""
from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import httpx
import win32crypt

API = 'https://api.jackandjill.ai'
CLERK = 'https://clerk.jackandjill.ai'
SESSION = Path(os.environ['LOCALAPPDATA']) / 'career-ops' / 'jack-and-jill' / 'session.dpapi'


class JackHTTPError(RuntimeError):
    def __init__(self, status_code, method, path):
        self.status_code = status_code
        super().__init__(f'Jack returned HTTP {status_code} for {method} {path}; no write was retried.')


def identifier(value: str) -> str:
    return str(uuid.UUID(value))


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.getinfo('word/document.xml').file_size > 10_000_000:
            raise ValueError('Jack DOCX text exceeds the inspection limit')
        root = ElementTree.fromstring(archive.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    tag = '{' + ns['w'] + '}'
    def visible(node):
        if node.tag in (tag + 'del', tag + 'moveFrom'):
            return ''
        if node.tag == tag + 't':
            return node.text or ''
        if node.tag in (tag + 'tab', tag + 'br'):
            return ' '
        return ''.join(visible(child) for child in node)
    return '\n'.join(visible(p) for p in root.findall('.//w:p', ns))


class JackClient:
    def __init__(self, client=None, session_path=SESSION):
        self.http = client or httpx.Client(timeout=60, follow_redirects=False)
        self.session_path = session_path
        self.token = None
        self.token_until = 0
        self.lock = threading.RLock()

    def _token(self):
        with self.lock:
            if self.token and time.monotonic() < self.token_until:
                return self.token
            if not self.session_path.exists():
                raise RuntimeError('Jack website session missing. Run the skill login helper; never print or paste tokens.')
            state = json.loads(win32crypt.CryptUnprotectData(self.session_path.read_bytes(), None, None, None, 0)[1])
            session_id = state['sessionId']
            if not isinstance(session_id, str) or not session_id.startswith('sess_') or not session_id.replace('_', '').isalnum():
                raise RuntimeError('Invalid saved Jack session ID')
            r = self.http.post(f'{CLERK}/v1/client/sessions/{session_id}/tokens',
                               params={'__clerk_api_version': '2025-11-10'},
                               headers={'Authorization': state['auth']}, data={})
            if r.status_code != 200:
                raise RuntimeError(f'Jack website sign-in needs renewal (HTTP {r.status_code}); no browser fallback was started.')
            data = r.json()
            self.token = (data.get('response') or data)['jwt']
            self.token_until = time.monotonic() + 35
            if r.headers.get('authorization') and r.headers['authorization'] != state['auth']:
                state['auth'] = r.headers['authorization']
                encrypted = win32crypt.CryptProtectData(json.dumps(state).encode(), 'Career Ops Jack session', None, None, None, 0)
                temp = self.session_path.with_suffix('.tmp')
                temp.write_bytes(encrypted)
                temp.replace(self.session_path)
            return self.token

    def request(self, method, path, **kwargs):
        if not path.startswith(('/candidate/', '/jack-chat/')) or '..' in path or '\\' in path:
            raise ValueError('Only the observed candidate and Jack chat APIs are permitted')
        r = self.http.request(method, API + path, headers={'Authorization': 'Bearer ' + self._token()}, **kwargs)
        if r.status_code >= 400:
            # Error payloads can echo private text and signed download URLs.
            raise JackHTTPError(r.status_code, method, path)
        return r.json()

    def cv(self, source_id=None, job_match_id=None):
        if bool(source_id) == bool(job_match_id):
            raise ValueError('Provide exactly one source CV ID or job match ID')
        path = f'application/{identifier(job_match_id)}' if job_match_id else identifier(source_id)
        return self.request('GET', f'/candidate/cv-document/{path}/latest')

    def content(self, version_id):
        data = self.request('GET', f'/candidate/cv-document/version/{identifier(version_id)}/content')
        raw = base64.b64decode(data['content_base64'], validate=True)
        if len(raw) > 20_000_000 or not zipfile.is_zipfile(io.BytesIO(raw)):
            raise RuntimeError('Jack did not return a valid DOCX')
        return raw

    def chat(self, content, message_id, on_event=None):
        if not isinstance(content, str) or not 1 <= len(content) <= 100_000:
            raise ValueError('Jack request must contain 1–100000 characters')
        identifier(message_id)
        ready = self.request('POST', '/jack-chat/connect', json={'onboarding_call': False, 'page_context': None})
        if ready.get('turn_in_progress'):
            raise RuntimeError('Jack already has a turn running. Wait for it; do not start a duplicate or stop the user’s turn.')
        if ready.get('spend_limit_exceeded'):
            raise RuntimeError('Jack usage limit reached; wait until the service reset instead of retrying')
        events = []
        def record(payload):
            if payload == '[DONE]':
                return
            event = json.loads(payload)
            if not str(event.get('type', '')).startswith('reasoning-'):
                events.append(event)
                if on_event:
                    on_event(event)
        with self.http.stream('POST', API + '/jack-chat/messages/stream',
                              headers={'Authorization': 'Bearer ' + self._token(), 'Accept': 'text/event-stream'},
                              json={'content': content, 'client_msg_id': message_id, 'file_ids': [], 'page_context': None}) as r:
            if r.status_code != 200:
                raise RuntimeError(f'Jack chat returned HTTP {r.status_code}; preserve message_id {message_id} if investigating delivery')
            lines = []
            for line in r.iter_lines():
                if line.startswith('data:'):
                    lines.append(line[5:].lstrip())
                elif not line and lines:
                    payload = '\n'.join(lines)
                    lines = []
                    record(payload)
            if lines:
                record('\n'.join(lines))
        return {'message_id': message_id, 'complete': any(e.get('type') == 'finish' for e in events),
                'events': [e for e in events if not str(e.get('type', '')).startswith('reasoning-')]}
