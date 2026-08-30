from __future__ import annotations
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python' / 'src'))
from atlas.triadic.governed_posture import assign_governed_posture
import atlas.triadic.human_review_ui as review_ui
from atlas.triadic.human_review_ui import HumanReviewError, create_app, load_sealed_run
from test_atlas_governed_posture import run

def sealed(root: Path) -> Path:
    run(root); assign_governed_posture(root)
    (root / 'run_manifest.json').write_text('{"logical_time":"t1","run_id":"r1"}\n')
    (root / 'grounding' / 'source.md').write_text('source\n')
    (root / 'grounding' / 'conversion_report.json').write_text('{}\n')
    (root / 'lifecycle_events.jsonl').write_text('{\"event\":\"review\"}\n')
    names = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    (root / 'checksums.sha256').write_text(
        ''.join(f'{hashlib.sha256((root/n).read_bytes()).hexdigest()}  {n}\n' for n in names),
        encoding='utf-8', newline='\n',
    )
    return root

def fields(body: str) -> dict[str,str]:
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', body))

def loopback_app(app):
    async def wrapper(scope, receive, send):
        scope = dict(scope); scope['client'] = ('127.0.0.1', 1)
        await app(scope, receive, send)
    return wrapper

def client(root): return TestClient(loopback_app(create_app(root)), base_url='http://127.0.0.1')


def make_directory_link(link: Path, target: Path) -> None:
    if os.name == 'nt':
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link), str(target)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)

def test_review_preview_commit_packet_and_receipt(tmp_path):
    root = sealed(tmp_path/'artifacts'/'run'); before = {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    c = client(root); review = c.get('/review'); assert review.status_code == 200
    assert review.text.count('<h1>') == 1 and '<fieldset>' in review.text and 'required type="radio"' in review.text
    assert review.text.count('type="radio"') == 4 and 'value="REPAIR"' in review.text
    assert 'Claims and citations' in review.text and 'Sophia' in review.text and review.headers['cache-control'] == 'no-store'
    csrf = fields(review.text)['csrf']
    preview = c.post('/review/preview', data={'csrf':csrf,'decision':'APPROVE','reviewer':'<Tom>','note':'<note>'})
    assert preview.status_code == 200; form = fields(preview.text); assert set(form) == {'csrf','confirmation_token'}
    committed = c.post('/review/commit', data={**form,'decision':'REJECT','reviewer':'evil','note':'evil'})
    assert committed.status_code == 200
    packet_path = next((root.parent/'human_decisions').glob('*/human_review_decision.json')); packet = json.loads(packet_path.read_text())
    assert packet['decision'] == 'APPROVE' and packet['reviewer']['display_name'] == '<Tom>' and 'note' not in packet
    assert set(packet_path.parent.iterdir()) == {packet_path, packet_path.with_suffix('.json.sha256'), packet_path.with_name('human_review_decision_receipt.html')}
    sidecar = packet_path.with_suffix('.json.sha256').read_bytes()
    assert sidecar == (
        f'{hashlib.sha256(packet_path.read_bytes()).hexdigest()}  human_review_decision.json\n'
    ).encode('ascii')
    assert b'\r' not in sidecar
    receipt = packet_path.with_name('human_review_decision_receipt.html').read_text(); assert '&lt;Tom&gt;' in receipt and 'logical time' in receipt and 'Sophia:' in receipt
    assert before == {p:p.read_bytes() for p in before}; assert c.get('/review').status_code == 409
    fresh = client(root).get('/review')
    assert fresh.status_code == 409 and 'Decision already recorded' in fresh.text

def test_rejections_are_bounded_and_no_packet_is_published(tmp_path):
    root = sealed(tmp_path/'artifacts'/'run'); before = {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    ordinary = TestClient(create_app(root), base_url='http://127.0.0.1'); assert ordinary.get('/review').status_code == 403
    c = client(root); csrf = fields(c.get('/review').text)['csrf']
    for data, status in [({'decision':'APPROVE','reviewer':'a','note':''},403), ({'csrf':csrf,'decision':'HOLD','reviewer':'a','note':''},400), ({'csrf':csrf,'confirmation_token':'unknown'},409)]:
        response = c.post('/review/commit' if 'confirmation_token' in data else '/review/preview', data=data)
        assert response.status_code == status
        if status == 400:
            assert 'Correct these fields' in response.text
        else:
            assert 'Request rejected' in response.text and csrf not in response.text
    assert not list((root.parent/'human_decisions').glob('*/human_review_decision.json')) and before == {p:p.read_bytes() for p in before}


def test_post_publish_sealed_conflict_rolls_back_owned_decision(tmp_path, monkeypatch):
    root = sealed(tmp_path/'artifacts'/'run')
    checks = iter((True, False))
    monkeypatch.setattr(review_ui, '_unchanged', lambda *_args: next(checks))
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    preview = c.post(
        '/review/preview',
        data={'csrf':csrf,'decision':'HOLD','reviewer':'Reviewer','note':'Concurrent conflict.'},
    )
    response = c.post('/review/commit', data=fields(preview.text))
    assert response.status_code == 409
    decisions = root.parent/'human_decisions'
    assert not list(decisions.glob('*/human_review_decision.json'))
    assert not list(decisions.glob('.rollback-*'))
    assert c.get('/review').status_code == 200

def test_dns_rebinding_hostname_is_rejected_even_if_it_resolves_to_loopback(tmp_path, monkeypatch):
    root = sealed(tmp_path/'artifacts'/'run')
    monkeypatch.setattr(
        socket,
        'getaddrinfo',
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 0))],
    )
    c = client(root)
    response = c.get(
        '/review',
        headers={'host':'attacker.test:8765','origin':'http://attacker.test:8765'},
    )
    assert response.status_code == 403
    assert 'REQUEST_HOST_NOT_LOOPBACK' in response.text

def test_oversized_review_member_is_rejected_before_full_read(tmp_path):
    root = sealed(tmp_path/'artifacts'/'run')
    with (root/'final_review.html').open('wb') as stream:
        stream.truncate(16*1024*1024+1)
    with pytest.raises(HumanReviewError, match='size limit'):
        load_sealed_run(root)
    with pytest.raises(HumanReviewError): load_sealed_run('relative')


def test_human_review_rejects_directory_junction_without_opening_external_member(
    tmp_path, monkeypatch,
):
    root = sealed(tmp_path/'artifacts'/'run')
    external = tmp_path/'external'
    external.mkdir()
    secret = external/'secret.txt'
    secret.write_text('must not reach Atlas', encoding='utf-8')
    make_directory_link(root/'linked', external)
    original_open = Path.open

    def reject_external_open(path, *args, **kwargs):
        if path.resolve(strict=False) == secret.resolve(strict=True):
            raise AssertionError('external junction member was opened')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', reject_external_open)
    with pytest.raises(HumanReviewError, match='unsafe'):
        load_sealed_run(root)


def test_human_review_parses_the_single_bounded_snapshot_without_reopening(tmp_path, monkeypatch):
    root = sealed(tmp_path/'artifacts'/'run')
    request = (root/'request.json').resolve(strict=True)
    original_open = Path.open
    opens = 0

    def single_open(path, *args, **kwargs):
        nonlocal opens
        if path.resolve(strict=False) == request:
            opens += 1
            if opens > 1:
                raise AssertionError('sealed request was reopened after bounded snapshot')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', single_open)
    assert load_sealed_run(root)['request']['run_id'] == 'r1'
    assert opens == 1


def test_existing_decision_scan_rejects_nested_junction_without_external_open(
    tmp_path, monkeypatch,
):
    root = sealed(tmp_path/'artifacts'/'run')
    c = client(root)
    decision_root = root.parent/'human_decisions'
    external = tmp_path/'external-decision'
    external.mkdir()
    secret = external/'human_review_decision.json'
    secret.write_text('{}\n', encoding='utf-8')
    make_directory_link(decision_root/'linked', external)
    original_open = Path.open

    def reject_external_open(path, *args, **kwargs):
        if path.resolve(strict=False) == secret.resolve(strict=True):
            raise AssertionError('external decision junction member was opened')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', reject_external_open)
    response = c.get('/review')
    assert response.status_code == 409
    assert 'could not be accepted' in response.text


@pytest.mark.parametrize('decision,note', [('HOLD', 'needs correction'), ('REJECT', 'not accepted')])
def test_hold_and_reject_preview_with_required_note(tmp_path, decision, note):
    root = sealed(tmp_path / 'artifacts' / 'run')
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    response = c.post('/review/preview', data={'csrf': csrf, 'decision': decision, 'reviewer': 'Reviewer', 'note': note})
    assert response.status_code == 200
    confirm = fields(response.text)
    committed = c.post('/review/commit', data=confirm)
    assert committed.status_code == 200
    packet = json.loads(next((root.parent/'human_decisions').glob('*/human_review_decision.json')).read_text())
    assert packet['decision'] == decision
    assert not (packet_path := next((root.parent/'human_decisions').glob('*/human_review_decision.json'))).with_name('repair_request.json').exists()


def test_repair_requires_note_and_emits_bound_child_lineage_request(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    missing = c.post('/review/preview', data={'csrf': csrf, 'decision': 'REPAIR', 'reviewer': 'Reviewer', 'note': ''})
    assert missing.status_code == 400
    assert 'A decision note is required for HOLD, REJECT, or REPAIR.' in missing.text
    assert not list((root.parent / 'human_decisions').glob('*/human_review_decision.json'))

    preview = c.post('/review/preview', data={'csrf': csrf, 'decision': 'REPAIR', 'reviewer': '<Reviewer>', 'note': 'Add bounded counterevidence.'})
    assert preview.status_code == 200
    assert 'repair_request_id' in preview.text and 'new_lineage_id' in preview.text
    confirmation = fields(preview.text)
    committed = c.post('/review/commit', data={**confirmation, 'decision': 'APPROVE', 'note': 'tampered'})
    assert committed.status_code == 200

    decision_path = next((root.parent / 'human_decisions').glob('*/human_review_decision.json'))
    decision_dir = decision_path.parent
    repair_path = decision_dir / 'repair_request.json'
    assert set(path.name for path in decision_dir.iterdir()) == {
        'human_review_decision.json', 'human_review_decision.json.sha256', 'human_review_decision_receipt.html',
        'repair_request.json', 'repair_request.json.sha256',
    }
    decision = json.loads(decision_path.read_text())
    repair = json.loads(repair_path.read_text())
    for member in (decision_path, repair_path):
        sidecar = member.with_name(member.name + '.sha256').read_bytes()
        assert sidecar == f'{hashlib.sha256(member.read_bytes()).hexdigest()}  {member.name}\n'.encode('ascii')
        assert b'\r' not in sidecar
    assert decision['decision'] == 'REPAIR' and decision['decision_note'] == 'Add bounded counterevidence.'
    assert repair['decision_id'] == decision['decision_id'] and repair['repair_note'] == decision['decision_note']
    assert uuid.UUID(repair['repair_request_id']) and uuid.UUID(repair['new_lineage_id'])
    assert repair['parent_run'] == {
        'run_id': 'r1', 'logical_time': 't1', 'run_manifest_path': 'run_manifest.json',
        'run_manifest_file_sha256': hashlib.sha256((root / 'run_manifest.json').read_bytes()).hexdigest(),
    }
    assert repair['parent_candidate'] == {
        'path': 'candidate_packet.json',
        'file_sha256': hashlib.sha256((root / 'candidate_packet.json').read_bytes()).hexdigest(),
    }
    assert repair['route'] == {
        'owner': 'Sonya', 'status': 'REQUESTED_NOT_EXECUTED', 'requires_new_governed_run': True,
        'requires_full_human_review': True, 'candidate_generation_performed': False,
        'candidate_revision_performed': False,
    }
    fresh = client(root).get('/review')
    assert fresh.status_code == 409 and 'Decision already recorded' in fresh.text
    assert repair['candidate_content_included'] is False
    assert all(value is False for value in repair['authority_boundary'].values())
    assert all(value is False for value in repair['side_effects'].values())
    binding = decision['repair_request_binding']
    assert binding['path'] == 'repair_request.json' and binding['repair_request_id'] == repair['repair_request_id']
    assert binding['new_lineage_id'] == repair['new_lineage_id']
    assert binding['file_sha256'] == hashlib.sha256(repair_path.read_bytes()).hexdigest()
    assert binding['canonical_sha256'] == hashlib.sha256(json.dumps(repair, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert repair_path.with_suffix('.json.sha256').read_text() == f"{binding['file_sha256']}  repair_request.json\n"
    receipt = (decision_dir / 'human_review_decision_receipt.html').read_text()
    assert '&lt;Reviewer&gt;' in receipt and 'Sonya requested, not executed' in receipt and 'No candidate content was generated or revised' in receipt
    assert before == {path: path.read_bytes() for path in before}
    assert c.post('/review/commit', data=confirmation).status_code == 409
    assert c.get('/review').status_code == 409


def test_tampered_repair_request_fails_closed_without_second_decision(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    preview = c.post('/review/preview', data={'csrf': csrf, 'decision': 'REPAIR', 'reviewer': 'Reviewer', 'note': 'Repair evidence.'})
    assert c.post('/review/commit', data=fields(preview.text)).status_code == 200
    decision_dirs = list((root.parent / 'human_decisions').iterdir())
    (decision_dirs[0] / 'repair_request.json.sha256').write_text('0' * 64 + '  repair_request.json\n')
    response = c.get('/review')
    assert response.status_code == 409 and 'could not be accepted' in response.text
    assert list((root.parent / 'human_decisions').iterdir()) == decision_dirs


def test_input_and_decision_root_bounds(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    with pytest.raises(HumanReviewError):
        create_app(root, root)
    with pytest.raises(HumanReviewError):
        create_app(root, root / 'human_decisions')
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    response = c.post('/review/preview', data={'csrf': csrf, 'decision': 'APPROVE', 'reviewer': 'x' * 201, 'note': ''})
    assert response.status_code == 400


@pytest.mark.parametrize('target', ['grounding/source.md', 'grounding/segments.jsonl', 'lifecycle_events.jsonl'])
def test_complete_eleven_target_ledger_rejects_supplemental_changes(tmp_path, target):
    root = sealed(tmp_path / 'artifacts' / 'run')
    assert len((root / 'checksums.sha256').read_text().splitlines()) == 11
    (root / target).write_text('altered\n')
    with pytest.raises(HumanReviewError):
        load_sealed_run(root)


def test_complete_ledger_rejects_an_unlisted_artifact(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    (root / 'unlisted.txt').write_text('not ledgered\n')
    with pytest.raises(HumanReviewError):
        load_sealed_run(root)

def test_privacy_browser_null_origin_form_post_is_authorized_by_loopback_and_csrf(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    response = c.post('/review/preview', headers={'origin': 'null', 'sec-fetch-site': 'same-origin'}, data={'csrf': csrf, 'decision': 'APPROVE', 'reviewer': 'Reviewer', 'note': ''})
    assert response.status_code == 200
    assert 'Confirm decision' in response.text


def test_cross_site_form_post_has_safe_reason_code(tmp_path):
    root = sealed(tmp_path / 'artifacts' / 'run')
    c = client(root)
    csrf = fields(c.get('/review').text)['csrf']
    response = c.post('/review/preview', headers={'origin': 'null', 'sec-fetch-site': 'cross-site'}, data={'csrf': csrf, 'decision': 'APPROVE', 'reviewer': 'Reviewer', 'note': ''})
    assert response.status_code == 403
    assert 'REQUEST_FETCH_SITE_CROSS_SITE' in response.text
    assert csrf not in response.text
