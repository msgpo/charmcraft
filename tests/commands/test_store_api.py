# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

"""Tests for the Store API layer (code in store/store.py)."""

import logging
from unittest.mock import patch, call, MagicMock

import pytest

from charmcraft.commands.store.store import Store


@pytest.fixture
def client_mock():
    client_mock = MagicMock()
    with patch('charmcraft.commands.store.store.Client', lambda: client_mock):
        yield client_mock


def test_login(client_mock):
    """Simple login case."""
    store = Store()
    result = store.login()
    assert client_mock.mock_calls == [
        call.clear_credentials(),
        call.get('/v1/whoami'),
    ]
    assert result is None


def test_logout(client_mock):
    """Simple logout case."""
    store = Store()
    result = store.logout()
    assert client_mock.mock_calls == [
        call.clear_credentials(),
    ]
    assert result is None


def test_whoami(client_mock):
    """Simple whoami case."""
    store = Store()
    auth_response = {'display-name': 'John Doe', 'username': 'jdoe', 'id': '-1'}
    client_mock.get.return_value = auth_response

    result = store.whoami()

    assert client_mock.mock_calls == [
        call.get('/v1/whoami'),
    ]
    assert result.name == 'John Doe'
    assert result.username == 'jdoe'
    assert result.userid == '-1'


def test_register_name(client_mock):
    """Simple whoami case."""
    store = Store()
    result = store.register_name('testname')

    assert client_mock.mock_calls == [
        call.post('/v1/charm', {'name': 'testname'}),
    ]
    assert result is None


def test_list_registered_names_empty(client_mock):
    """List registered names getting an empty response."""
    store = Store()

    auth_response = {'charms': []}
    client_mock.get.return_value = auth_response

    result = store.list_registered_names()

    assert client_mock.mock_calls == [
        call.get('/v1/charm')
    ]
    assert result == []


def test_list_registered_names_multiple(client_mock):
    """List registered names getting a multiple response."""
    store = Store()

    auth_response = {'charms': [
        {'name': 'name1', 'private': False, 'status': 'status1'},
        {'name': 'name2', 'private': True, 'status': 'status2'},
    ]}
    client_mock.get.return_value = auth_response

    result = store.list_registered_names()

    assert client_mock.mock_calls == [
        call.get('/v1/charm')
    ]
    item1, item2 = result
    assert item1.name == 'name1'
    assert not item1.private
    assert item1.status == 'status1'
    assert item2.name == 'name2'
    assert item2.private
    assert item2.status == 'status2'


def test_upload_straightforward(client_mock, caplog):
    """The full and successful upload case."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    store = Store()

    # the first response, for when pushing bytes
    test_upload_id = 'test-upload-id'
    client_mock.push.return_value = test_upload_id

    # the second response, for telling the store it was pushed
    test_status_url = 'https://store.c.c/status'
    client_mock.post.return_value = {'status-url': test_status_url}

    # the third response, status ok (note the patched UPLOAD_ENDING_STATUSES below)
    test_revision = 123
    test_status_ok = 'test-status'
    status_response = {'revisions': [{'status': test_status_ok, 'revision': test_revision}]}
    client_mock.get.return_value = status_response

    test_status_resolution = 'test-ok-or-not'
    fake_statuses = {test_status_ok: test_status_resolution}
    test_charm_name = 'test-name'
    test_filepath = 'test-filepath'
    with patch.dict('charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES', fake_statuses):
        result = store.upload(test_charm_name, test_filepath)

    # check all client calls
    assert client_mock.mock_calls == [
        call.push(test_filepath),
        call.post('/v1/charm/{}/revisions'.format(test_charm_name), {'upload-id': test_upload_id}),
        call.get(test_status_url),
    ]

    # check result (build after patched ending struct)
    assert result.ok == test_status_resolution
    assert result.status == test_status_ok
    assert result.revision == test_revision

    # check logs
    expected = [
        "Upload test-upload-id started, got status url https://store.c.c/status",
        "Status checked: " + str(status_response),
    ]
    assert expected == [rec.message for rec in caplog.records]


def test_upload_polls_status(client_mock, caplog):
    """Upload polls status url until the end is indicated."""
    caplog.set_level(logging.DEBUG, logger="charmcraft.commands")
    store = Store()

    # first and second response, for pushing bytes and let the store know about it
    test_upload_id = 'test-upload-id'
    client_mock.push.return_value = test_upload_id
    test_status_url = 'https://store.c.c/status'
    client_mock.post.return_value = {'status-url': test_status_url}

    # the status checking response, will answer something not done yet twice, then ok
    test_revision = 123
    test_status_ok = 'test-status'
    status_response_1 = {'revisions': [{'status': 'still-scanning', 'revision': None}]}
    status_response_2 = {'revisions': [{'status': 'more-revisions', 'revision': None}]}
    status_response_3 = {'revisions': [{'status': test_status_ok, 'revision': test_revision}]}
    client_mock.get.side_effect = [status_response_1, status_response_2, status_response_3]

    test_status_resolution = 'clean and crispy'
    fake_statuses = {test_status_ok: test_status_resolution}
    with patch.dict('charmcraft.commands.store.store.UPLOAD_ENDING_STATUSES', fake_statuses):
        with patch('charmcraft.commands.store.store.POLL_DELAY', 0.01):
            result = store.upload('some-name', 'some-filepath')

    # check the status-checking client calls (kept going until third one)
    assert client_mock.mock_calls[2:] == [
        call.get(test_status_url),
        call.get(test_status_url),
        call.get(test_status_url),
    ]

    # check result which must have values from final result
    assert result.ok == test_status_resolution
    assert result.status == test_status_ok
    assert result.revision == test_revision

    # check logs
    expected = [
        "Upload test-upload-id started, got status url https://store.c.c/status",
        "Status checked: " + str(status_response_1),
        "Status checked: " + str(status_response_2),
        "Status checked: " + str(status_response_3),
    ]
    assert expected == [rec.message for rec in caplog.records]
