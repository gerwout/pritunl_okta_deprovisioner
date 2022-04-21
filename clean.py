import requests
import urllib.parse
import time
import uuid
import hmac
import hashlib
import base64
import sys
import argparse

def query_yes_no(question, default="no"):
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' " "(or 'y' or 'n').\n")

def __parse_link_header(link_header):
    return_dict = {}
    links = link_header.split(",")
    for idx, link in enumerate(links):
        items = link.split('; ')
        if len(items) == 2:
            href = items[0].strip('<> ')
            type = items[1].replace('rel=', '').replace('"', '')
            return_dict[type] = href

    return return_dict

def __fetch_users(url):
    print("Fetching: " + url)
    okta_headers = {'Content-Type': 'application/json','Accept':'application/json', 'Authorization':'SSWS ' +
                                                                                                    OKTA_API_KEY}
    r = requests.get(url, headers=okta_headers)
    # get the next link if there is any pagination
    link_headers = __parse_link_header(r.headers.get('link', ''))

    return r.json(), link_headers

def okta_fetch_users():
    users, links = __fetch_users(OKTA_DOMAIN + OKTA_USERS_URL)
    # ok, we have pagination
    while links.get('next', None) is not None:
        new_users, new_links = __fetch_users(links.get('next', None))
        users = users + new_users
        links = new_links
    print("There are " + str(len(users)) + " active users in Okta")

    return users

def pritunl_auth_request(method, path, headers=None, data=None):
    auth_timestamp = str(int(time.time()))
    auth_nonce = uuid.uuid4().hex
    auth_string = '&'.join([PRITUNL_API_TOKEN, auth_timestamp, auth_nonce, method.upper(), path])
    auth_signature = base64.b64encode(hmac.new(PRITUNL_API_SECRET.encode('utf-8'), auth_string.encode('utf-8'), hashlib.sha256).digest())
    auth_headers = {
        'Auth-Token': PRITUNL_API_TOKEN,
        'Auth-Timestamp': auth_timestamp,
        'Auth-Nonce': auth_nonce,
        'Auth-Signature': auth_signature,
    }
    if headers:
        auth_headers.update(headers)
    print(method.upper() + " " + PRITUNL_DOMAIN + path)
    return getattr(requests, method.lower())(
        PRITUNL_DOMAIN + path,
        headers=auth_headers,
        data=data,
    )

def main():
    pritunl_users = []
    okta_users = []
    users = []
    to_delete = []

    pritunl_orgs = pritunl_auth_request('get', '/organization').json()
    for idx, org in enumerate(pritunl_orgs):
        pritunl_users = pritunl_users + pritunl_auth_request('get', '/user/' + org['id']).json()

    for idx, user in enumerate(pritunl_users):
        auth_type = user['auth_type']
        email = user['email']
        if email is None:
            email = ''
        else:
            email = email.lower()
        # we are only going to clean up users that authenticate with Okta
        if auth_type == "saml_okta":
            users.append({'email': email, 'prit_id': user['id'], 'prit_org_id': user['organization']})

    print("There are " + str(len(users)) + " users in Pritunl")
    # get all active users from Okta
    active_users = okta_fetch_users()
    for idx, user in enumerate(active_users):
        okta_users.append(user['profile']['email'].lower())

    # now lets loop through all pritunl users and see if their email appears in the Okta users list
    for idx, prit_user in enumerate(users):
        email = prit_user['email']
        # we found a user that should be deleted!
        if not email in okta_users:
            to_delete.append(prit_user)

    del_count = len(to_delete)
    print("There are " + str(del_count) + " users that can be deleted from Pritunl")
    print("")
    for idx, del_user in enumerate(to_delete):
        print("email: " + del_user['email'] + " id: " + del_user['prit_id'] + " org_id: " + del_user['prit_org_id'])
    print("")
    if del_count > 0 and query_yes_no("Are you certain that you want to delete the above users from Pritunl?"):
        for idx, del_user in enumerate(to_delete):
            email = del_user['email']
            id = del_user['prit_id']
            org_id = del_user['prit_org_id']
            del_url = "/user/" + org_id + "/" + id
            pritunl_auth_request('delete', del_url)
            print("Deleted " + email + " id: " + id + " org_id: " + org_id)
    elif del_count > 0:
        print("Cancelled the delete action")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Remove Pritunl users that are no longer active in Okta')
    parser.add_argument('--sso_domain', required=True, help='Okta domain (i.e. https://companyname.okta.com)', default="")
    parser.add_argument('--pritunl_domain', required=True, help='Pritunl domain name (i.e. https://vpn.company.com)', default="")
    parser.add_argument('--okta_api_key', required=True, help='Okta api key', default="")
    parser.add_argument('--pritunl_api_key', required=True, help='Pritunl API key', default="")
    parser.add_argument('--pritunl_api_secret', required=True, help='Pritunl API secret', default="")

    # show help when no arguments are given
    if len(sys.argv) == 1:
        parser.print_help(sys.stdout)
        sys.exit(0)

    args = parser.parse_args()
    OKTA_DOMAIN = args.sso_domain
    OKTA_LIMIT = 200
    OKTA_USERS_URL = "/api/v1/users?limit=" + str(OKTA_LIMIT) + "&search=" + urllib.parse.quote("status eq \"ACTIVE\"")
    OKTA_API_KEY = args.okta_api_key
    PRITUNL_DOMAIN = args.pritunl_domain
    PRITUNL_API_TOKEN = args.pritunl_api_key
    PRITUNL_API_SECRET = args.pritunl_api_secret
    main()