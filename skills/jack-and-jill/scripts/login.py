"""Normal Clerk email-code login for Jack, with Windows-user encrypted session storage."""
import argparse
import datetime
import json
import re
import time

import httpx
import win32crypt

from jack_client import CLERK, SESSION, JackClient

PENDING = SESSION.with_name('pending.dpapi')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = win32crypt.CryptProtectData(json.dumps(data).encode(), 'Career Ops Jack session', None, None, None, 0)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(raw)
    temp.replace(path)


def load(path):
    return json.loads(win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1])


def clerk_post(client, path, body, auth=None):
    r = client.post(CLERK + '/v1/client/sign_ins' + path, params={'__clerk_api_version': '2025-11-10'},
                    headers={'Authorization': auth} if auth else {}, data=body)
    data = r.json()
    if r.status_code != 200:
        codes = ', '.join(e.get('code', 'unknown') for e in data.get('errors', []))
        raise RuntimeError(f'Jack sign-in stopped: HTTP {r.status_code} ({codes}). Do not bypass a verification challenge.')
    return data['response'], r.headers.get('authorization') or auth


def outlook_code(since, email):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        ns = win32com.client.Dispatch('Outlook.Application').GetNamespace('MAPI')
        if ns.GetDefaultFolder(6).Parent.Name.casefold() != email.casefold():
            raise RuntimeError('Default Outlook mailbox does not match the requested Jack login email')
        for folder_number in (6, 23):
            items = ns.GetDefaultFolder(folder_number).Items
            items.Sort('[ReceivedTime]', True)
            for index in range(1, min(items.Count, 20) + 1):
                item = items.Item(index)
                if item.Class != 43:
                    continue
                # Outlook COM returns local wall-clock values on this profile.
                if item.ReceivedTime.replace(tzinfo=None) < since:
                    continue
                if str(item.SenderEmailAddress).casefold() != 'notifications@jackandjill.ai':
                    continue
                subject = str(item.Subject)
                if 'verification code' in subject.casefold():
                    match = re.search(r'\b\d{6}\b', subject)
                    if match:
                        return match.group()
        return None
    finally:
        pythoncom.CoUninitialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email')
    parser.add_argument('--code')
    parser.add_argument('--outlook', action='store_true', help='Read only the new Jack verification code from the matching local Outlook mailbox')
    parser.add_argument('--check', action='store_true', help='Verify the existing saved session without creating a new login')
    args = parser.parse_args()
    if args.check:
        result = JackClient().request('GET', '/candidate/info')
        print(json.dumps({'connected': True, 'candidate_id': result['candidate_id']}))
        return
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        if args.email:
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', args.email):
                parser.error('Provide a valid existing Jack account email')
            response, auth = clerk_post(client, '', {'identifier': args.email})
            factor = next((f for f in response.get('supported_first_factors', []) if f['strategy'] == 'email_code'), None)
            if not factor:
                raise RuntimeError('This account does not offer normal email-code sign-in; use its required authentication flow')
            since = datetime.datetime.now() - datetime.timedelta(seconds=3)
            response, auth = clerk_post(client, '/' + response['id'] + '/prepare_first_factor',
                                         {'strategy': 'email_code', 'email_address_id': factor['email_address_id']}, auth)
            pending = {'signInId': response['id'], 'auth': auth, 'email': args.email,
                       'startedAt': since.isoformat()}
            save(PENDING, pending)
        elif args.code:
            pending = load(PENDING)
        else:
            parser.error('Use --check, --email EMAIL [--outlook], or --code CODE')
        code = args.code
        if args.outlook and not code:
            since = datetime.datetime.fromisoformat(pending['startedAt'])
            for attempt in range(15):
                code = outlook_code(since, pending['email'])
                if code:
                    break
                time.sleep(2)
        if not code:
            print('Jack sent a verification email. The pending login is encrypted; finish with --code CODE. No session was replaced.')
            return
        if not re.fullmatch(r'\d{6}', code):
            raise ValueError('Verification code must be six digits')
        response, auth = clerk_post(client, '/' + pending['signInId'] + '/attempt_first_factor',
                                     {'strategy': 'email_code', 'code': code}, pending['auth'])
        if response.get('status') != 'complete' or not response.get('created_session_id'):
            raise RuntimeError('Jack requires another authentication step; the existing session was preserved')
        save(SESSION, {'auth': auth, 'sessionId': response['created_session_id'], 'createdAt': datetime.datetime.now().isoformat()})
        save(PENDING, {'completed': True})
        print('Jack website session saved with Windows-user encryption. No browser was used.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        parser_message = str(exc)
        print(json.dumps({'error': parser_message}))
        raise SystemExit(1)
