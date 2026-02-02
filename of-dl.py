#!/usr/bin/env python3

import hashlib
import json
import os
import pathlib
import shutil
import sys
from datetime import UTC, datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

######################
# CONFIGURATIONS     #
######################

# Session Variables (update every time you login or your browser updates)
USER_ID = '545268099'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'
)
X_BC = '5515f3df80a8c16ba2d95bd16728e5f36a6e417c'
SESS_COOKIE = 'r9h0j3cuen8fjj65mfqja9e6s0'

# 0 = do not print file names or api calls
# 1 = print filenames only when max_age is set
# 2 = always print filenames
# 3 = print api calls
# 4 = print skipped files that already exist
VERBOSITY = 2
# Download Directory. Uses CWD if null
DL_DIR = ''
# List of accounts to skip
ByPass: list[str] = ['']

# Separate photos into subdirectories by post/album (Single photo posts are not put into subdirectories)
ALBUMS = True
# Use content type subfolders (messgaes/archived/stories/purchased), or download everything to /profile/photos and /profile/videos
USE_SUB_FOLDERS = True

# Content types to download
VIDEOS = True
PHOTOS = False
AUDIO = True
POSTS = True
STORIES = True
MESSAGES = True
ARCHIVED = True
PURCHASED = True

######################
# END CONFIGURATIONS #
######################


API_URL = 'https://onlyfans.com/api2/v2'
new_files = 0
MAX_AGE = 0
LATEST = 0
API_HEADER: dict[str, str] = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Encoding': 'gzip, deflate',
    'app-token': '33d57ade8c02dbc5a333db99ff9ae26a',
    'User-Agent': USER_AGENT,
    'x-bc': X_BC,
    'user-id': USER_ID,
    'Cookie': 'auh_id=' + USER_ID + '; sess=' + SESS_COOKIE,
}


def create_signed_headers(link, queryParams) -> None:
    global API_HEADER
    path = '/api2/v2' + link
    if queryParams:
        query = '&'.join('='.join((key, val)) for (key, val) in queryParams.items())
        path: str = f'{path}?{query}'
    unixtime = str(int(datetime.now().timestamp()))
    msg: str = '\n'.join([dynamic_rules['static_param'], unixtime, path, USER_ID])
    message: bytes = msg.encode('utf-8')
    hash_object: hashlib.HASH = hashlib.sha1(message)
    sha_1_sign: str = hash_object.hexdigest()
    sha_1_b: bytes = sha_1_sign.encode('ascii')
    checksum: int = (
        sum([sha_1_b[number] for number in dynamic_rules['checksum_indexes']]) + dynamic_rules['checksum_constant']
    )
    format: str = dynamic_rules['prefix'] + ':{}:{:x}:' + dynamic_rules['suffix']
    API_HEADER['sign'] = format.format(sha_1_sign, abs(checksum))
    API_HEADER['time'] = unixtime
    return


def showAge(myStr) -> str:
    myStr = str(myStr)
    tmp: list[str] = myStr.split('.')
    t = int(tmp[0])
    dt_obj: datetime = datetime.fromtimestamp(t)
    strOut: str = dt_obj.strftime('%Y-%m-%d')
    return strOut


def latest(profile) -> str:
    latest = '0'
    dirpath: list[str]
    dirs: list[str]
    files: list[str]
    for dirpath, dirs, files in os.walk(profile):
        for f in files:
            if f.startswith('20'):
                latest: str = f if f > latest else latest
    return latest[:10]


def api_request(endpoint, apiType):
    posts_limit = 50
    age = ''
    getParams: dict[str, str] = {'limit': str(posts_limit), 'order': 'publish_date_asc'}
    if apiType == 'messages':
        getParams['order'] = 'desc'
    if apiType == 'subscriptions':
        getParams['type'] = 'active'
    if (
        MAX_AGE and apiType != 'messages' and apiType != 'purchased' and apiType != 'subscriptions'
    ):  # Cannot be limited by age
        getParams['afterPublishTime'] = str(MAX_AGE) + '.000000'
        age: str = ' age ' + str(showAge(getParams['afterPublishTime']))
        # Messages can only be limited by offset or last message ID. This requires its own separate function. TODO
    create_signed_headers(endpoint, getParams)
    if VERBOSITY >= 3:
        print(f'{API_URL}{endpoint}{age}')

    status = requests.get(API_URL + endpoint, headers=API_HEADER, params=getParams)
    if status.ok:
        list_base = status.json()
    else:
        return json.loads('{"error":{"message":"http ' + str(status.status_code) + '"}}')

    # Fixed the issue with the maximum limit of 50 posts by creating a kind of "pagination"
    if (len(list_base) >= posts_limit and apiType != 'user-info') or ('hasMore' in list_base and list_base['hasMore']):
        if apiType == 'messages':
            getParams['id'] = str(list_base['list'][len(list_base['list']) - 1]['id'])
        elif apiType == 'purchased' or apiType == 'subscriptions':
            getParams['offset'] = str(posts_limit)
        else:
            getParams['afterPublishTime'] = list_base[len(list_base) - 1]['postedAtPrecise']
        while True:
            create_signed_headers(endpoint, getParams)
            if VERBOSITY >= 3:
                print(f'{API_URL}{endpoint}{age}')
            status: requests.Response = requests.get(API_URL + endpoint, headers=API_HEADER, params=getParams)
            if status.ok:
                list_extend = status.json()
            else:
                list_extend = None
            if list_extend is not None:
                if apiType == 'messages':
                    list_base['list'].extend(list_extend['list'])
                    if not list_extend['hasMore'] or len(list_extend['list']) < posts_limit or not status.ok:
                        break
                    getParams['id'] = str(list_base['list'][len(list_base['list']) - 1]['id'])
                    continue
                list_base.extend(list_extend)  # Merge with previous posts
                if len(list_extend) < posts_limit:
                    break
                if apiType == 'purchased' or apiType == 'subscriptions':
                    getParams['offset'] = str(int(getParams['offset']) + posts_limit)
                else:
                    getParams['afterPublishTime'] = list_extend[len(list_extend) - 1]['postedAtPrecise']
    return list_base


def get_user_info(profile):
    # <profile> = "me" -> info about yourself
    info = api_request('/users/' + profile, 'user-info')
    if 'error' in info:
        print(f'\nFailed to get user:  {profile}\n{info["error"]["message"]}\n')
    return info


def get_subscriptions() -> list[str]:
    subs = api_request('/subscriptions/subscribes', 'subscriptions')
    if 'error' in subs:
        print(f'\nSUBSCRIPTIONS ERROR: {subs["error"]["message"]}')
        return ['error', 'error']
    return [row['username'] for row in subs]


def download_media(media, subtype, postdate, album='') -> None:
    filename = postdate + '_' + str(media['id'])

    if 'source' in media:
        source = media['source']['source']
    elif 'files' in media:
        if 'full' in media['files']:
            if media['files']['full']['url'] is not None:
                source = media['files']['full']['url']
            else:
                source = media['files']['preview']['url']
        elif 'preview' in media:
            source = media['preview']
        else:
            return
    else:
        return

    if source is None:
        return

    if (
        media['type'] != 'photo' and media['type'] != 'video' and media['type'] != 'audio' and media['type'] != 'gif'
    ) or not media['canView']:
        return
    if (
        (media['type'] == 'photo' and not PHOTOS)
        or (media['type'] == 'video' and not VIDEOS)
        or (media['type'] == 'audio' and not AUDIO)
    ):
        return

    extension = source.split('?')[0].split('.')[-1]
    ext = '.' + extension
    if len(ext) < 3:
        return

    if ALBUMS and album and media['type'] == 'photo':
        path = '/photos/' + postdate + '_' + album + '/' + filename + ext
    else:
        path = '/' + media['type'] + 's/' + filename + ext
    if USE_SUB_FOLDERS and subtype != 'posts':
        path = '/' + subtype + path
    if not os.path.isdir(PROFILE + os.path.dirname(path)):
        pathlib.Path(PROFILE + os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    if not os.path.isfile(PROFILE + path):
        if VERBOSITY >= 2 or (MAX_AGE and VERBOSITY >= 1):
            print(f'{PROFILE}{path}')
        global new_files
        new_files += 1
        try:
            r: requests.Response = requests.get(source, stream=True, timeout=(4, None), verify=False)
        except Exception:
            print(f'Error getting: {source} (skipping)')
            return
        if r.status_code != 200:
            print(f'{r.url} :: {str(r.status_code)}')
            return
        # Writing to a temp file while downloading, so if we interrupt
        # a file, we will not skip it but re-download it at next time.
        with open(PROFILE + path + '.part', 'wb') as f:
            r.raw.decode_content = True
            shutil.copyfileobj(r.raw, f)
        r.close()
        # Downloading finished, remove temp file.
        shutil.move(PROFILE + path + '.part', PROFILE + path)
    else:
        if VERBOSITY >= 4:
            print(f'{path} ... already exists')


def get_content(MEDIATYPE, API_LOCATION) -> None:
    posts = api_request(API_LOCATION, MEDIATYPE)
    if 'error' in posts:
        print(f'\nERROR: {API_LOCATION} :: {posts["error"]["message"]}')
    if MEDIATYPE == 'messages':
        posts = posts['list']
    if len(posts) > 0:
        print(f'Found  {str(len(posts))} {MEDIATYPE}')
        for post in posts:
            if 'media' not in post or ('canViewMedia' in post and not post['canViewMedia']):
                continue
            if MEDIATYPE == 'purchased' and ('fromUser' not in post or post['fromUser']['username'] != PROFILE):
                continue  # Only get paid posts from PROFILE
            if 'postedAt' in post:  # get post date
                postdate = str(post['postedAt'][:10])
            elif 'createdAt' in post:
                postdate = str(post['createdAt'][:10])
            else:
                postdate = '1970-01-01'  # epoc failsafe if date is not present
            if len(post['media']) > 1:  # Don't put single photo posts in a subfolder
                album = str(post['id'])  # album ID
            else:
                album = ''
            for media in post['media']:
                if MEDIATYPE == 'stories':
                    if media['createdAt'] is None:
                        postdate = str(media['id'])
                    else:
                        postdate = str(media['createdAt'][:10])
                if (
                    'source' in media
                    and 'source' in media['source']
                    and media['source']['source']
                    and ('canView' not in media or media['canView'])
                ) or ('files' in media and 'canView' in media and media['canView']):
                    download_media(media, MEDIATYPE, postdate, album)
        global new_files
        print(f'Downloaded {str(new_files)} new {MEDIATYPE}')
        new_files = 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'\nUsage: {sys.argv[0]}  <list of profiles / all> <max age (optional)>\n')
        print('max age must be an integer. number of days back from today.\n')
        print(
            'if max age = 0, the script will find the latest date amongst the files for each profile independantly.\n'
        )
        print('Make sure to update the session variables at the top of this script (See readme).\n')
        print('Update Browser User Agent (Every time it updates): https://ipchicken.com/\n')
        exit()

        try:
            os.chdir(DL_DIR)
        except FileNotFoundError:
            print(f'Unable to use DIR: {DL_DIR}')
    print(f'CWD = {os.getcwd()}')
    # rules for the signed headers
    dynamic_rules = {
        'end': '69406376',
        'start': '51892',
        'format': '51892:{}:{:x}:69406376',
        'prefix': '51892',
        'suffix': '69406376',
        'revision': '202502031617-af2daeeb87',
        'app_token': '33d57ade8c02dbc5a333db99ff9ae26a',
        'static_param': '7HMjX3tp4B4JJDOryHAMCUIQCtmGq69D',
        'remove_headers': ['user_id'],
        'checksum_indexes': [
            15,
            35,
            3,
            7,
            21,
            26,
            39,
            35,
            4,
            0,
            6,
            29,
            35,
            28,
            37,
            27,
            22,
            4,
            9,
            10,
            37,
            21,
            27,
            13,
            17,
            31,
            28,
            24,
            0,
            14,
            9,
            0,
        ],
        'checksum_constant': 53,
    }
    PROFILE_LIST: list[str] = sys.argv
    PROFILE_LIST.pop(0)
    if PROFILE_LIST[-1] == '0':
        LATEST = 1
        PROFILE_LIST.pop(-1)
    if len(PROFILE_LIST) > 1 and PROFILE_LIST[-1].isnumeric():
        MAX_AGE = int((datetime.today() - timedelta(int(PROFILE_LIST.pop(-1)))).timestamp())
        print(f'\nGetting posts newer than {datetime.fromtimestamp(int(MAX_AGE), UTC)} UTC')

    if PROFILE_LIST[0] == 'all':
        PROFILE_LIST = get_subscriptions()

    for PROFILE in PROFILE_LIST:
        if PROFILE in ByPass:
            if VERBOSITY > 0:
                print(f'skipping {PROFILE}')
            continue
        user_info = get_user_info(PROFILE)

        if 'id' in user_info:
            PROFILE_ID = str(user_info['id'])
        else:
            continue

        if LATEST:
            latestDate: str = latest(PROFILE)
            if latestDate != '0':
                MAX_AGE = int(datetime.strptime(latestDate + ' 00:00:00', '%Y-%m-%d %H:%M:%S').timestamp())
                print(f'\nGetting posts newer than {latestDate} 00:00:00 UTC')

        if os.path.isdir(PROFILE):
            print(f'\n {PROFILE} exists.\nDownloading new media, skipping pre-existing.')
        else:
            print(f'\nDownloading content to {PROFILE}')

        if POSTS:
            get_content('posts', '/users/' + PROFILE_ID + '/posts')
        if ARCHIVED:
            get_content('archived', '/users/' + PROFILE_ID + '/posts/archived')
        if STORIES:
            get_content('stories', '/users/' + PROFILE_ID + '/stories')
        if MESSAGES:
            get_content('messages', '/chats/' + PROFILE_ID + '/messages')
        if PURCHASED:
            get_content('purchased', '/posts/paid/all')
