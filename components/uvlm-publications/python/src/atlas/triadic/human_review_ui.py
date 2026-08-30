"""Loopback-only, transaction-bound local human-review decision capture."""
from __future__ import annotations
import argparse, hashlib, html, ipaddress, json, os, secrets, shutil, socket, uuid, webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import parse_qs
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
class HumanReviewError(ValueError): pass
class RequestRejected(PermissionError):
 def __init__(self, code): self.code=code
REQUIRED=("request.json","grounding/manifest.json","candidate_packet.json","sophia_audit_packet.json","atlas_posture_packet.json","final_review.html","run_manifest.json","checksums.sha256")
TOTALITY_REQUEST_SCHEMA='uvlm.coherence.totality.request_envelope.v1'
TOTALITY_TEL_REQUIRED=('tel_events.jsonl','tel_finalization_receipt.json')
ATLAS_PACKET_KEYS=('schema_id','schema_version','packet_type','producer_repository','producer','run_id','logical_time','candidate_id','audit_id','input_digests','parent_list','sophia_disposition','sophia_reason_codes','sophia_findings','retention_posture','publication_posture','expiry_posture','revocation_posture','pmr_posture','candidate_is_not_answer','full_posterior_presented','top_k_is_presentation_only','human_action_required','requires_human_review','human_decision','human_decision_options','limitations','nonauthority','side_effects','nonauthority_statement')
ATLAS_NONAUTH=('truth_certification','final_answer_authority','memory_write_authority','pmr_write_authority','training_authority','canonization','publication','doi_mutation','crossref_deposit','catalog_mutation','knowledge_graph_mutation','deployment','release','model_invocation','candidate_alteration','sophia_alteration','external_action_authority','automatic_phase_advance')
ATLAS_SIDE_EFFECTS=('network_access_performed','model_invocation_performed','candidate_mutation_performed','sophia_mutation_performed','source_mutation_performed','memory_write_performed','pmr_write_performed','training_performed','canonization_performed','publication_performed','doi_mutated','crossref_deposit_performed','catalog_mutated','knowledge_graph_mutated','deployment_performed','release_performed')
SOPHIA_NONAUTH=('truth_certification','final_answer_authority','memory_write_authority','training_authority','canonization','publication','deployment','release','human_decision')
SOPHIA_SIDE_EFFECTS=('network_access_performed','model_invocation_performed','candidate_mutation_performed','source_mutation_performed','memory_write_performed','training_performed','canonization_performed','publication_performed','deployment_performed','release_performed','pmr_write_performed')
ATLAS_POSTURES={'PASS':('retain_for_human_review','publication_blocked_pending_human_review'),'HOLD':('quarantine','do_not_publish'),'REJECT':('rejected','do_not_publish')}
ATLAS_STATEMENT='Atlas presents bounded evidence and posture only. It does not certify truth or authorize memory, PMR, training, canonization, publication, deployment, release, or any external action.'
AUTH=("truth_certification","final_answer_authority","memory_write_authority","pmr_write_authority","canonization","publication","doi_mutation","crossref_deposit","catalog_mutation","knowledge_graph_mutation","deployment","release","model_invocation","candidate_alteration","sophia_alteration","atlas_posture_alteration","external_action_authority","automatic_phase_advance")
EFFECTS=("network_access_beyond_loopback","model_invocation_performed","candidate_mutation_performed","sophia_mutation_performed","atlas_posture_mutation_performed","sealed_run_mutation_performed","memory_write_performed","pmr_write_performed","canonization_performed","publication_performed","doi_mutated","crossref_deposit_performed","catalog_mutated","knowledge_graph_mutated","deployment_performed","release_performed")
DECISIONS=("APPROVE","HOLD","REJECT","REPAIR")
NOTE_REQUIRED=("HOLD","REJECT","REPAIR")
REPAIR_AUTH=AUTH+("repair_execution_authority","lineage_activation_authority")
REPAIR_EFFECTS=EFFECTS+("repair_execution_performed","child_candidate_generation_performed")
REPAIR_KEYS=("schema_id","schema_version","packet_type","repair_request_id","decision_id","decision","generated_at_utc","reviewer","repair_note","parent_run","parent_candidate","new_lineage_id","route","candidate_content_included","authority_boundary","side_effects","nonauthority")
RAW_QUARANTINE_PATH='sonya/raw_output.quarantine'
MAX_RAW_QUARANTINE_BYTES=2*1024*1024
MAX_REVIEW_MEMBER_BYTES=16*1024*1024
MAX_REVIEW_TREE_BYTES=64*1024*1024
REVIEWER_MAX=200
NOTE_MAX=4000
FORM_MAX=16*1024
HEADERS={"Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","Cache-Control":"no-store"}
@dataclass
class _OpaqueMember:
 path:Path
 size:int
 declared_sha256:str|None=None
def _sha(b)->str:
 if isinstance(b,_OpaqueMember):
  if not _hex(b.declared_sha256):raise HumanReviewError('opaque sealed member is not ledger-bound')
  return b.declared_sha256
 return hashlib.sha256(b).hexdigest()
def _size(value):return value.size if isinstance(value,_OpaqueMember) else len(value)
def _canon(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _link_like(path:Path)->bool:
 try:
  probe=getattr(path,'is_junction',None)
  return path.is_symlink() or bool(probe and probe())
 except OSError:return True
def _member_safe(root:Path,path:Path)->bool:
 try:
  relative=path.relative_to(root);cursor=root
  for part in relative.parts:
   cursor/=part
   if _link_like(cursor):return False
  path.resolve(strict=True).relative_to(root)
  return True
 except (OSError,ValueError):return False
def _walk_members(root:Path)->list[Path]:
 members=[];pending=[root]
 while pending:
  directory=pending.pop()
  try:children=sorted(directory.iterdir(),key=lambda item:item.name)
  except OSError as e:raise HumanReviewError('sealed artifact is unreadable') from e
  directories=[]
  for path in children:
   if not _member_safe(root,path):raise HumanReviewError('sealed artifact is unsafe')
   members.append(path)
   if path.is_dir():directories.append(path)
  pending.extend(reversed(directories))
 return sorted(members,key=lambda item:item.relative_to(root).as_posix())
def _pairs(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError
  d[k]=v
 return d
def _constant(v):raise ValueError
def _path_bytes(p:Path,limit=MAX_REVIEW_MEMBER_BYTES)->bytes:
 try:
  if _link_like(p) or _link_like(p.parent) or not p.is_file() or p.stat().st_size>limit:raise ValueError
  with p.open('rb') as stream:raw=stream.read(limit+1)
  if len(raw)>limit:raise ValueError
  return raw
 except (OSError,ValueError) as e:raise HumanReviewError('bounded artifact is invalid or unreadable') from e
def _json(p:Path)->dict:
 try:
  raw=_path_bytes(p)
  if b'\0' in raw:raise ValueError
  obj=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
 except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError) as e:raise HumanReviewError('sealed JSON artifact is invalid') from e
 if not isinstance(obj,dict):raise HumanReviewError('sealed JSON artifact is invalid')
 return obj
def _jsonl(p:Path)->list[dict]:
 try:
  raw=_path_bytes(p)
  if not raw or not raw.endswith(b'\n') or b'\0' in raw:raise ValueError
  rows=[]
  for line in raw.splitlines(keepends=True):
   obj=json.loads(line.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
   if not isinstance(obj,dict) or line!=_canon(obj)+b'\n':raise ValueError
   rows.append(obj)
  return rows
 except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError) as e:raise HumanReviewError('sealed TEL artifact is invalid') from e
def _root(v):
 p=Path(v)
 if not p.is_absolute() or _link_like(p) or p==Path(p.anchor):raise HumanReviewError('run root is invalid')
 p=p.resolve()
 if not p.is_dir():raise HumanReviewError('run root is invalid')
 return p
def _files(root):
 out={};total=0
 for path in _walk_members(root):
  if not path.is_file():continue
  try:name=path.relative_to(root).as_posix()
  except ValueError as e:raise HumanReviewError('sealed artifact is unsafe') from e
  if name in out:raise HumanReviewError('sealed artifact inventory is invalid')
  try:size=path.stat().st_size
  except OSError as e:raise HumanReviewError('sealed artifact is unreadable') from e
  limit=MAX_RAW_QUARANTINE_BYTES if name.casefold()==RAW_QUARANTINE_PATH.casefold() else MAX_REVIEW_MEMBER_BYTES
  total+=size
  if size>limit or total>MAX_REVIEW_TREE_BYTES:raise HumanReviewError('sealed artifact size limit exceeded')
  if name.casefold()==RAW_QUARANTINE_PATH.casefold():out[name]=_OpaqueMember(path=path,size=size)
  else:
   try:
    with path.open('rb') as stream:data=stream.read(limit+1)
   except OSError as e:raise HumanReviewError('sealed artifact is unreadable') from e
   if len(data)>limit:raise HumanReviewError('sealed artifact size limit exceeded')
   out[name]=data
 if not set(REQUIRED)<=set(out):raise HumanReviewError('sealed required artifact is invalid')
 return out
def _checks(files):
 try:
  raw=files['checksums.sha256']
  if not raw or not raw.endswith(b'\n') or b'\r' in raw:raise ValueError
  lines=raw[:-1].decode('utf-8').split('\n')
 except UnicodeDecodeError as e:raise HumanReviewError('checksum file is invalid') from e
 except ValueError as e:raise HumanReviewError('checksum file is invalid') from e
 if b'\0' in raw:raise HumanReviewError('checksum file is invalid')
 got={}
 for line in lines:
  parts=line.split('  ',1)
  if len(parts)!=2:raise HumanReviewError('checksum file is invalid')
  digest,target=parts
  if len(digest)!=64 or digest.lower()!=digest or any(c not in '0123456789abcdef' for c in digest):raise HumanReviewError('checksum file is invalid')
  if not target or target.startswith('/') or '\\' in target or target in {'.','..'} or '..' in Path(target).parts or target in got:raise HumanReviewError('checksum file is invalid')
  got[target]=digest
 names=set(files)-{'checksums.sha256'}
 for name in names:
  if isinstance(files[name],_OpaqueMember):files[name].declared_sha256=got.get(name)
 expected=''.join(f'{got[name]}  {name}\n' for name in sorted(got)).encode('utf-8')
 if raw!=expected or set(got)!=names or any(got[n]!=_sha(files[n]) for n in names):raise HumanReviewError('sealed checksum verification failed')
def _unchanged(root,expected):
 current=_files(root);_checks(current);return current==expected
def _inventory(files,exclude=()):
 return [{'path':name,'sha256':_sha(files[name]),'bytes':_size(files[name])} for name in sorted(set(files)-set(exclude))]
def _exact(value,keys):return isinstance(value,dict) and set(value)==set(keys)
def _hex(value,length=64):return isinstance(value,str) and len(value)==length and all(c in '0123456789abcdef' for c in value)
def _false_exact(value,keys):return _exact(value,keys) and all(item is False for item in value.values())
def _totality_packet_contract(files,req,cand,sop,atlas):
 expected=ATLAS_POSTURES.get(sop.get('disposition'))
 producer={'repository':'pdxvoiceteacher/uvlm-publications','role':'bounded_totality_posture_and_human_review_renderer','version':'1.0'}
 if (
  not _exact(atlas,ATLAS_PACKET_KEYS)
  or atlas.get('schema_id')!='uvlm.atlas.totality.posture_packet.v1' or atlas.get('schema_version')!='1.0' or atlas.get('packet_type')!='atlas_posture_packet'
  or atlas.get('producer_repository')!='pdxvoiceteacher/uvlm-publications' or atlas.get('producer')!=producer
  or atlas.get('sophia_disposition')!=sop.get('disposition') or expected is None
  or (atlas.get('retention_posture'),atlas.get('publication_posture'))!=expected
  or atlas.get('expiry_posture')!='review_bounded' or atlas.get('revocation_posture')!='revocable' or atlas.get('pmr_posture')!='separate_consent_no_action'
  or any(atlas.get(name) is not True for name in ('candidate_is_not_answer','full_posterior_presented','top_k_is_presentation_only','human_action_required','requires_human_review'))
  or atlas.get('human_decision')!='PENDING' or atlas.get('human_decision_options')!=list(DECISIONS)
  or not isinstance(atlas.get('limitations'),list) or not atlas['limitations'] or any(not isinstance(item,str) or not item for item in atlas['limitations'])
  or atlas.get('sophia_reason_codes')!=sop.get('reason_codes') or atlas.get('sophia_findings')!=sop.get('findings')
  or not _false_exact(atlas.get('nonauthority'),ATLAS_NONAUTH) or not _false_exact(atlas.get('side_effects'),ATLAS_SIDE_EFFECTS)
  or atlas.get('nonauthority_statement')!=ATLAS_STATEMENT
  or not _false_exact(sop.get('nonauthority'),SOPHIA_NONAUTH) or not _false_exact(sop.get('side_effects'),SOPHIA_SIDE_EFFECTS)
  or sop.get('requires_human_review') is not True
 ):
  raise HumanReviewError('sealed totality authority or posture contract is invalid')
 digests=atlas.get('input_digests');parents=atlas.get('parent_list')
 if not isinstance(digests,dict) or not isinstance(parents,list):raise HumanReviewError('sealed Atlas parent contract is invalid')
 sophia_digest=digests.get('sophia_audit_packet.json')
 prefix_digest=digests.get('tel_audit_prefix.jsonl')
 if (
  not isinstance(sophia_digest,dict) or sophia_digest.get('file_sha256')!=_sha(files['sophia_audit_packet.json'])
  or not isinstance(prefix_digest,dict) or prefix_digest.get('file_sha256')!=_sha(files['tel_audit_prefix.jsonl'])
 ):
  raise HumanReviewError('sealed Atlas parent contract is invalid')
 expected_paths={name for name,value in digests.items() if isinstance(value,dict) and value.get('file_sha256') is not None}
 observed={}
 for parent in parents:
  if not _exact(parent,('artifact_type','path','file_sha256','canonical_sha256')) or parent.get('artifact_type')!='bounded_input' or parent.get('path') in observed:raise HumanReviewError('sealed Atlas parent contract is invalid')
  observed[parent.get('path')]=parent
 if set(observed)!=expected_paths or any({k:observed[name].get(k) for k in ('file_sha256','canonical_sha256')}!={k:digests[name].get(k) for k in ('file_sha256','canonical_sha256')} for name in observed):raise HumanReviewError('sealed Atlas parent contract is invalid')
 if files['sophia_audit_packet.json']!=_canon(sop)+b'\n' or files['atlas_posture_packet.json']!=_canon(atlas)+b'\n':raise HumanReviewError('sealed totality packet is not canonical')
def _totality_tel_contract(files,req,manifest,cand,sop,atlas,tel,receipt):
 receipt_keys=('schema_id','run_id','logical_time','candidate_id','audit_id','decision_id','tel_audit_prefix_sha256','sophia_audit_packet_sha256','atlas_posture_packet_sha256','tel_events_sha256','event_count','human_decision','external_continuation_required','effects','authority_effect')
 effect_keys=('network','provider_invocation','memory_write','training','publication','deployment','release')
 if (
  not _exact(receipt,receipt_keys) or files['tel_finalization_receipt.json']!=_canon(receipt)+b'\n'
  or receipt.get('schema_id')!='uvlm.coherence.totality.tel_finalization_receipt.v1'
  or receipt.get('run_id')!=req.get('run_id') or receipt.get('logical_time')!=req.get('logical_time')
  or receipt.get('candidate_id')!=cand.get('candidate_id') or receipt.get('audit_id')!=sop.get('audit_id') or receipt.get('audit_id')!=atlas.get('audit_id')
  or receipt.get('event_count')!=18 or receipt.get('human_decision')!='PENDING' or receipt.get('external_continuation_required') is not True
  or not _false_exact(receipt.get('effects'),effect_keys) or receipt.get('authority_effect')!='NONE'
  or receipt.get('tel_audit_prefix_sha256')!=_sha(files['tel_audit_prefix.jsonl'])
  or receipt.get('sophia_audit_packet_sha256')!=_sha(files['sophia_audit_packet.json'])
  or receipt.get('atlas_posture_packet_sha256')!=_sha(files['atlas_posture_packet.json'])
  or receipt.get('tel_events_sha256')!=_sha(files['tel_events.jsonl'])
 ):
  raise HumanReviewError('sealed totality TEL finalization receipt is invalid')
 prefix_rows=_jsonl_from_bytes(files['tel_audit_prefix.jsonl'],'TEL audit prefix')
 if len(prefix_rows)!=15 or tel[:15]!=prefix_rows:raise HumanReviewError('sealed totality TEL prefix is invalid')
 quarantine=_json_from_bytes(files.get('sonya/quarantine_receipt.json'),'quarantine receipt')
 claim_map=_json_from_bytes(files.get('claim_evidence_map.json'),'claim map')
 ucm=_json_from_bytes(files.get('ucm_state.json'),'UCM state')
 projector=_json_from_bytes(files.get('projector_receipt.json'),'projector receipt')
 aha=_json_from_bytes(files.get('aha_result.json'),'AHA result')
 counterexamples=_json_from_bytes(files.get('counterexamples.json'),'counterexamples')
 waveform=_json_from_bytes(files.get('reference_waveform.json'),'reference waveform')
 aperture=_json_from_bytes(files.get('aperture_decision.json'),'aperture decision')
 pmr=_json_from_bytes(files.get('pmr_receipt.json'),'PMR receipt')
 event_order=('REQUEST_CANONICALIZED','GROUNDING_VERIFIED','RAW_OUTPUT_QUARANTINED','CANDIDATE_CANONICALIZED','CLAIM_EVIDENCE_MAPPED','UCM_PROJECTED','AHA_EVALUATED','COUNTEREXAMPLES_SCANNED','REFERENCE_WAVEFORM_ENCODED','APERTURE_DECIDED','PMR_BOUNDARY_RECORDED','SOPHIA_AUDIT_REQUESTED','ATLAS_ORIENTATION_PENDING','HUMAN_DECISION_PENDING','CORE_BUILD_COMPLETED','SOPHIA_AUDIT_COMPLETED','ATLAS_ORIENTATION_COMPLETED','ROUTE_COMPLETED_HUMAN_PENDING')
 payloads={
  'REQUEST_CANONICALIZED':{'request_sha256':_sha(files['request.json'])},
  'GROUNDING_VERIFIED':{'grounding_manifest_sha256':_sha(files['grounding/manifest.json'])},
  'RAW_OUTPUT_QUARANTINED':{'raw_output_sha256':quarantine.get('raw_output_sha256')},
  'CANDIDATE_CANONICALIZED':{'candidate_sha256':_sha(files['candidate_packet.json'])},
  'CLAIM_EVIDENCE_MAPPED':{'claim_map_sha256':_sha(files['claim_evidence_map.json'])},
  'UCM_PROJECTED':{'ucm_state_sha256':_sha(files['ucm_state.json']),'projector_receipt_sha256':_sha(files['projector_receipt.json'])},
  'AHA_EVALUATED':{'aha_result_sha256':_sha(files['aha_result.json'])},
  'COUNTEREXAMPLES_SCANNED':{'counterexamples_sha256':_sha(files['counterexamples.json']),'unresolved_count':counterexamples.get('unresolved_count')},
  'REFERENCE_WAVEFORM_ENCODED':{'reference_waveform_sha256':_sha(files['reference_waveform.json']),'physical_frequency_claim':False},
  'APERTURE_DECIDED':{'aperture_decision_sha256':_sha(files['aperture_decision.json']),'decision':aperture.get('decision')},
  'PMR_BOUNDARY_RECORDED':{'pmr_receipt_sha256':_sha(files['pmr_receipt.json']),'persistent_bytes_written':0},
  'SOPHIA_AUDIT_REQUESTED':{'status':'REQUESTED_NOT_EXECUTED'},
  'ATLAS_ORIENTATION_PENDING':{'status':'PENDING_SOPHIA'},
  'HUMAN_DECISION_PENDING':{'status':'PENDING','external_receipt_required':True},
  'CORE_BUILD_COMPLETED':{'stop_boundary':'BEFORE_SOPHIA_AND_ATLAS'},
  'SOPHIA_AUDIT_COMPLETED':{'sophia_audit_packet_sha256':_sha(files['sophia_audit_packet.json']),'disposition':sop.get('disposition')},
  'ATLAS_ORIENTATION_COMPLETED':{'atlas_posture_packet_sha256':_sha(files['atlas_posture_packet.json']),'human_decision':'PENDING'},
  'ROUTE_COMPLETED_HUMAN_PENDING':{'tel_audit_prefix_sha256':_sha(files['tel_audit_prefix.jsonl']),'external_human_decision_receipt_required':True,'human_decision':'PENDING'},
 }
 outcomes=dict.fromkeys(event_order,'SUCCESS')
 outcomes['UCM_PROJECTED']={'PASS_SCREEN':'SUCCESS','HOLD':'HOLD','REFUSE':'REFUSE'}.get(projector.get('disposition'))
 outcomes['AHA_EVALUATED']='REFUSE' if aha.get('disposition')=='REJECTED' else ('HOLD' if aha.get('status')=='UNAVAILABLE' else 'SUCCESS')
 outcomes['APERTURE_DECIDED']={'PASS_SCREEN':'SUCCESS','HOLD':'HOLD','REFUSE':'REFUSE'}.get(aperture.get('decision'))
 for name in event_order[10:15]+event_order[16:]:outcomes[name]='RECORDED'
 outcomes['SOPHIA_AUDIT_COMPLETED']={'PASS':'SUCCESS','HOLD':'HOLD','REJECT':'REFUSE'}.get(sop.get('disposition'))
 event_keys=('schema_id','sequence','logical_time','event_type','run_id','candidate_id','audit_id','decision_id','outcome','payload','authority_effect')
 for index,(event_type,row) in enumerate(zip(event_order,tel),start=1):
  expected_candidate=cand.get('candidate_id') if index>=4 else None
  expected_audit=sop.get('audit_id') if index>=12 else None
  expected_decision=receipt.get('decision_id') if index>=14 else None
  if (
   not _exact(row,event_keys) or row.get('schema_id')!='uvlm.coherence.totality.tel_event.v1' or row.get('sequence')!=index or row.get('logical_time')!=f'T+{index:06d}'
   or row.get('event_type')!=event_type or row.get('run_id')!=req.get('run_id') or row.get('candidate_id')!=expected_candidate or row.get('audit_id')!=expected_audit or row.get('decision_id')!=expected_decision
   or row.get('outcome')!=outcomes[event_type] or row.get('payload')!=payloads[event_type] or row.get('authority_effect')!='NONE'
  ):raise HumanReviewError('sealed totality TEL semantic binding is invalid')
def _repository_identity(value):
 return (
  _exact(value,('repository','commit','tree','prefix_trees','worktree_clean','status_sha256'))
  and isinstance(value.get('repository'),str) and bool(value['repository'])
  and _hex(value.get('status_sha256')) and isinstance(value.get('worktree_clean'),bool)
  and _exact(value.get('prefix_trees'),('coherence_lattice','sophia','uvlm_publications'))
  and all(_hex(item,40) or _hex(item,64) for item in (value.get('commit'),value.get('tree'),*value.get('prefix_trees',{}).values()))
 )
def _totality_seal(files,request,manifest):
 effects=('network','provider_invocation','memory_write','training','canonization','publication','deployment','release','truth_certification')
 expected_effects=dict.fromkeys(effects,False)
 manifest_keys=('schema_id','run_id','logical_time','request_sha256','candidate_sha256','core_manifest_sha256','sealed_artifact_manifest_sha256','repository_identity','effect_ceiling','artifact_count','artifact_bytes','artifacts','authority_effect','human_review_required')
 if not _exact(manifest,manifest_keys) or files['run_manifest.json']!=_canon(manifest)+b'\n':raise HumanReviewError('sealed run manifest is invalid')
 rows=_inventory(files,('run_manifest.json','checksums.sha256'))
 if (
  manifest.get('schema_id')!='uvlm.coherence.totality.run_manifest.v1'
  or manifest.get('authority_effect')!='NONE' or manifest.get('human_review_required') is not True
  or manifest.get('effect_ceiling')!=expected_effects or not _repository_identity(manifest.get('repository_identity'))
  or manifest.get('artifacts')!=rows or manifest.get('artifact_count')!=len(rows)
  or manifest.get('artifact_bytes')!=sum(row['bytes'] for row in rows)
  or manifest.get('request_sha256')!=_sha(files['request.json'])
  or manifest.get('candidate_sha256')!=_sha(files['candidate_packet.json'])
  or manifest.get('core_manifest_sha256')!=_sha(files.get('core_manifest.json',b''))
  or manifest.get('sealed_artifact_manifest_sha256')!=_sha(files.get('sealed_artifact_manifest.json',b''))
 ):raise HumanReviewError('sealed run manifest verification failed')
 sealed=_json_from_bytes(files.get('sealed_artifact_manifest.json'), 'sealed artifact manifest')
 sealed_keys=('schema_id','run_id','logical_time','repository_identity','effect_ceiling','payload_count','payload_bytes','files','authority_effect')
 payload=_inventory(files,('sealed_artifact_manifest.json','run_manifest.json','checksums.sha256'))
 if (
  not _exact(sealed,sealed_keys) or files['sealed_artifact_manifest.json']!=_canon(sealed)+b'\n'
  or sealed.get('schema_id')!='uvlm.coherence.totality.sealed_artifact_manifest.v1'
  or sealed.get('run_id')!=manifest.get('run_id') or sealed.get('logical_time')!=manifest.get('logical_time')
  or sealed.get('repository_identity')!=manifest.get('repository_identity')
  or sealed.get('effect_ceiling')!=expected_effects or sealed.get('authority_effect')!='NONE'
  or sealed.get('files')!=payload or sealed.get('payload_count')!=len(payload)
  or sealed.get('payload_bytes')!=sum(row['bytes'] for row in payload)
 ):raise HumanReviewError('sealed artifact manifest verification failed')
 core=_json_from_bytes(files.get('core_manifest.json'),'core manifest')
 core_keys=('schema_id','run_id','logical_time','manifest_scope','post_core_artifacts_excluded','artifact_count','artifact_bytes','artifacts','authority_effect')
 post=('atlas_posture_packet.json','checksums.sha256','final_review.html','run_manifest.json','sealed_artifact_manifest.json','sophia_audit_packet.json','tel_events.jsonl','tel_finalization_receipt.json')
 core_payload=_inventory(files,('core_manifest.json',*post))
 if (
  not _exact(core,core_keys) or files['core_manifest.json']!=_canon(core)+b'\n'
  or core.get('schema_id')!='uvlm.coherence.totality.core_manifest.v1'
  or core.get('run_id')!=request.get('run_id') or core.get('logical_time')!=request.get('logical_time')
  or core.get('manifest_scope')!='IMMUTABLE_CORE_BUILD_BEFORE_EXTERNAL_AUDIT'
  or core.get('post_core_artifacts_excluded')!=list(post) or core.get('authority_effect')!='NONE'
  or core.get('artifacts')!=core_payload or core.get('artifact_count')!=len(core_payload)
  or core.get('artifact_bytes')!=sum(row['bytes'] for row in core_payload)
 ):raise HumanReviewError('sealed core manifest verification failed')
def _json_from_bytes(raw,label):
 try:
  if not isinstance(raw,bytes) or b'\0' in raw:raise ValueError
  value=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
 except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as e:raise HumanReviewError(f'{label} is invalid') from e
 if not isinstance(value,dict):raise HumanReviewError(f'{label} is invalid')
 return value
def _jsonl_from_bytes(raw,label):
 try:
  if not isinstance(raw,bytes) or not raw or not raw.endswith(b'\n') or b'\0' in raw:raise ValueError
  rows=[]
  for line in raw.splitlines(keepends=True):
   value=json.loads(line.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
   if not isinstance(value,dict) or line!=_canon(value)+b'\n':raise ValueError
   rows.append(value)
  return rows
 except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as e:raise HumanReviewError(f'{label} is invalid') from e
def load_sealed_run(v):
 root=_root(v);files=_files(root);_checks(files);names=REQUIRED[:5]+('run_manifest.json',);req,man,cand,sop,atlas,run=(_json_from_bytes(files[n],n) for n in names)
 ids=[(x.get('run_id'),x.get('logical_time')) for x in (req,cand,sop,atlas,run)]
 if not all(x==ids[0] for x in ids) or not all(ids[0]):raise HumanReviewError('sealed run identity mismatch')
 if sop.get('disposition') not in {'PASS','HOLD','REJECT'} or atlas.get('requires_human_review') is not True or atlas.get('human_decision')!='PENDING':raise HumanReviewError('sealed review is not eligible')
 sealed={'root':root,'files':files,'hashes':{n:_sha(b) for n,b in files.items()},'request':req,'manifest':man,'candidate':cand,'sophia':sop,'atlas':atlas,'raw_quarantine_bytes_loaded':False}
 if req.get('schema_id')==TOTALITY_REQUEST_SCHEMA:
  _totality_seal(files,req,run)
  if not set(TOTALITY_TEL_REQUIRED)<=set(files):raise HumanReviewError('sealed totality TEL artifacts are missing')
  _totality_packet_contract(files,req,cand,sop,atlas)
  tel=_jsonl_from_bytes(files['tel_events.jsonl'],'tel_events.jsonl');finalization=_json_from_bytes(files['tel_finalization_receipt.json'],'tel_finalization_receipt.json')
  order=('REQUEST_CANONICALIZED','GROUNDING_VERIFIED','RAW_OUTPUT_QUARANTINED','CANDIDATE_CANONICALIZED','CLAIM_EVIDENCE_MAPPED','UCM_PROJECTED','AHA_EVALUATED','COUNTEREXAMPLES_SCANNED','REFERENCE_WAVEFORM_ENCODED','APERTURE_DECIDED','PMR_BOUNDARY_RECORDED','SOPHIA_AUDIT_REQUESTED','ATLAS_ORIENTATION_PENDING','HUMAN_DECISION_PENDING','CORE_BUILD_COMPLETED','SOPHIA_AUDIT_COMPLETED','ATLAS_ORIENTATION_COMPLETED','ROUTE_COMPLETED_HUMAN_PENDING')
  if tuple(row.get('event_type') for row in tel)!=order or len(tel)!=18:raise HumanReviewError('sealed totality TEL order is invalid')
  _totality_tel_contract(files,req,man,cand,sop,atlas,tel,finalization)
  parent=tel[-1];decision_id=parent.get('decision_id')
  if finalization.get('decision_id')!=decision_id or not isinstance(decision_id,str) or not decision_id:raise HumanReviewError('sealed totality TEL binding is invalid')
  sealed['tel_rows']=tel;sealed['tel_finalization']=finalization
 if 'claim_evidence_map.json' in files:
  claim_map=_json_from_bytes(files['claim_evidence_map.json'],'claim_evidence_map.json')
  if claim_map.get('run_id')!=req.get('run_id') or claim_map.get('candidate_id')!=cand.get('candidate_id') or claim_map.get('candidate_sha256')!=_sha(files['candidate_packet.json']) or not isinstance(claim_map.get('claims'),list):raise HumanReviewError('sealed claim evidence is invalid')
  sealed['claim_map']=claim_map
 return sealed
def _decision_root(s,v):
 p=Path(v) if v else s['root'].parent/'human_decisions'
 if not p.is_absolute() or _link_like(p):raise HumanReviewError('decision root is invalid')
 p=p.resolve()
 try:p.relative_to(s['root'].parent)
 except ValueError as e:raise HumanReviewError('decision root is invalid') from e
 try:p.relative_to(s['root'])
 except ValueError:pass
 else:raise HumanReviewError('decision root is invalid')
 p.mkdir(parents=True,exist_ok=True)
 if _link_like(p) or not p.is_dir():raise HumanReviewError('decision root is invalid')
 return p
def _sidecar_payload(path:Path,limit=MAX_REVIEW_MEMBER_BYTES):
 side=path.with_name(path.name+'.sha256')
 try:
  raw=_path_bytes(path,limit);side_raw=_path_bytes(side,4096)
  return raw if side_raw==f'{_sha(raw)}  {path.name}\n'.encode('utf-8') else None
 except HumanReviewError:return None
def _sidecar_valid(path:Path)->bool:return _sidecar_payload(path) is not None
def _valid_uuid(value:Any)->bool:
 try:return str(uuid.UUID(str(value)))==value
 except (ValueError,TypeError,AttributeError):return False
def _repair_valid(decision:dict,request:dict,request_raw:bytes)->bool:
 binding=decision.get('repair_request_binding')
 expected_binding={'artifact_type':'bounded_repair_request','path':'repair_request.json','file_sha256':_sha(request_raw),'canonical_sha256':_sha(_canon(request)),'repair_request_id':request.get('repair_request_id'),'new_lineage_id':request.get('new_lineage_id')}
 parent_run=request.get('parent_run');parent_candidate=request.get('parent_candidate');route=request.get('route');evidence=decision.get('evidence_bindings')
 return (
  set(request)==set(REPAIR_KEYS) and request.get('schema_id')=='uvlm.bounded_repair_request.v1' and request.get('schema_version')=='1.0' and request.get('packet_type')=='bounded_repair_request'
  and request.get('decision')=='REPAIR' and request.get('decision_id')==decision.get('decision_id') and request.get('repair_note')==decision.get('decision_note')
  and request.get('generated_at_utc')==decision.get('generated_at_utc') and request.get('reviewer')==decision.get('reviewer')
  and _valid_uuid(request.get('repair_request_id')) and _valid_uuid(request.get('new_lineage_id')) and binding==expected_binding
  and isinstance(evidence,dict) and parent_run=={'run_id':decision.get('run_id'),'logical_time':decision.get('logical_time'),'run_manifest_path':'run_manifest.json','run_manifest_file_sha256':evidence.get('run_manifest.json')}
  and parent_candidate=={'path':'candidate_packet.json','file_sha256':evidence.get('candidate_packet.json')}
  and route=={'owner':'Sonya','status':'REQUESTED_NOT_EXECUTED','requires_new_governed_run':True,'requires_full_human_review':True,'candidate_generation_performed':False,'candidate_revision_performed':False}
  and request.get('candidate_content_included') is False and request.get('authority_boundary')==dict.fromkeys(REPAIR_AUTH,False) and request.get('side_effects')==dict.fromkeys(REPAIR_EFFECTS,False)
  and request.get('nonauthority')=='This artifact records a bounded Sonya-routed repair request and establishes a child lineage identifier only. It does not execute repair, generate or revise candidate content, or grant authority.'
 )
def _tel_continuation_valid(decision:dict,path:Path,decision_raw:bytes)->bool:
 try:
  tel_raw=_sidecar_payload(path)
  if tel_raw is None:return False
  rows=_jsonl_from_bytes(tel_raw,path.name)
  if len(rows)!=19:return False
  parent_raw=b''.join(_canon(row)+b'\n' for row in rows[:-1]);event=rows[-1];payload=event.get('payload')
  evidence=decision.get('evidence_bindings')
  return (
   isinstance(evidence,dict) and evidence.get('tel_events.jsonl')==_sha(parent_raw)
   and event=={
    'schema_id':'uvlm.coherence.totality.tel_event.v1','sequence':19,'logical_time':'T+000019','event_type':'HUMAN_DECISION_RECORDED',
    'run_id':decision.get('run_id'),'candidate_id':decision.get('candidate_id'),'audit_id':decision.get('audit_id'),'decision_id':decision.get('decision_id'),
    'outcome':'RECORDED','payload':{'decision_receipt_sha256':_sha(decision_raw),'disposition':decision.get('decision'),'external_receipt_path':'human_review_decision.json','parent_sealed_tel_sha256':_sha(parent_raw)},'authority_effect':'NONE'
   }
   and rows[-2].get('candidate_id')==decision.get('candidate_id') and rows[-2].get('audit_id')==decision.get('audit_id') and rows[-2].get('decision_id')==decision.get('decision_id')
  )
 except (OSError,HumanReviewError):return False
def _existing(out,rid):
 found=[]
 try:children=sorted(out.iterdir(),key=lambda item:item.name)
 except OSError as e:raise HumanReviewError('decision root is invalid') from e
 for directory in children:
  if _link_like(directory):raise HumanReviewError('existing decision is invalid')
  if not directory.is_dir():continue
  p=directory/'human_review_decision.json'
  if not p.exists():continue
  if not _member_safe(out,p):raise HumanReviewError('existing decision is invalid')
  decision_raw=_sidecar_payload(p)
  if decision_raw is None:raise HumanReviewError('existing decision is invalid')
  d=_json_from_bytes(decision_raw,p.name);receipt=p.with_name('human_review_decision_receipt.html')
  if d.get('decision') not in DECISIONS or not receipt.is_file() or _link_like(receipt):raise HumanReviewError('existing decision is invalid')
  repair=p.with_name('repair_request.json');repair_side=p.with_name('repair_request.json.sha256')
  if d.get('decision')=='REPAIR':
   repair_raw=_sidecar_payload(repair)
   if repair_raw is None or not _repair_valid(d,_json_from_bytes(repair_raw,repair.name),repair_raw):raise HumanReviewError('existing decision is invalid')
  elif d.get('repair_request_binding') is not None or repair.exists() or repair_side.exists():raise HumanReviewError('existing decision is invalid')
  if isinstance(d.get('evidence_bindings'),dict) and 'tel_finalization_receipt.json' in d['evidence_bindings']:
   if not _tel_continuation_valid(d,p.with_name('tel_human_continuation.jsonl'),decision_raw):raise HumanReviewError('existing decision is invalid')
  if d.get('run_id')==rid:found.append(p.parent)
 if len(found)>1:raise HumanReviewError('existing decision conflict')
 return found[0] if found else None
def _esc(x):return html.escape(str(x),quote=True)
def _response(body,status=200):return HTMLResponse('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Atlas human review</title></head><body>'+body+'</body></html>',status_code=status,headers=HEADERS)
def _host(host):
 if host.startswith('['):
  if ']' not in host:return None
  return host[1:host.index(']')]
 return host.rsplit(':',1)[0] if host.count(':')==1 else host
def _loop_ip(value):
 try:return ipaddress.ip_address(value).is_loopback
 except ValueError:return False
def _loop(v):return isinstance(v,str) and (v.casefold()=='localhost' or _loop_ip(v))
def _form(req):
 body=req.scope['_body']
 if len(body)>FORM_MAX:raise HumanReviewError('form is too large')
 try:return {k:v[-1] for k,v in parse_qs(body.decode(),keep_blank_values=True).items()}
 except UnicodeDecodeError as e:raise HumanReviewError('form is invalid') from e
def _reviewer_text(value):
 value=value.strip()
 if not value or len(value)>REVIEWER_MAX or any(ord(c)<32 or 127<=ord(c)<=159 for c in value):raise HumanReviewError('form field is invalid')
 return value
def _note_text(value):
 value=value.strip()
 if value and (len(value)>NOTE_MAX or any((ord(c)<32 and c not in '\n\r') or 127<=ord(c)<=159 for c in value)):raise HumanReviewError('form field is invalid')
 return value
def _claims_html(sealed):
 c=sealed['candidate'];claim_map=sealed.get('claim_map')
 if claim_map is None:
  return ''.join(f'<li>{_esc(x.get("claim_id"))}: {_esc(x.get("text"))}; {_esc(x.get("uncertainty"))}; {_esc(x.get("support_status"))}; {_esc(x.get("candidate_maturity"))}<ul>'+''.join(f'<li>{_esc(y.get("segment_id"))}: {_esc(y.get("segment_sha256"))}; {_esc(y.get("source_ordinal"))}; {_esc(y.get("exact_excerpt"))}</li>' for y in x.get('citations',[]) if isinstance(y,dict))+'</ul></li>' for x in c.get('claims',[]) if isinstance(x,dict))
 candidate_claims={x.get('claim_id'):x for x in c.get('claims',[]) if isinstance(x,dict)}
 rows=[]
 for record in claim_map['claims']:
  if not isinstance(record,dict):continue
  claim=candidate_claims.get(record.get('claim_id'),{});evidence=[]
  for item in record.get('evidence',[]):
   if not isinstance(item,dict):continue
   span=item.get('source_span') if isinstance(item.get('source_span'),dict) else {}
   evidence.append(f'<li>{_esc(item.get("segment_id"))}: exact excerpt “{_esc(item.get("exact_excerpt"))}”; character span {_esc(span.get("char_start"))}–{_esc(span.get("char_end"))}; byte span {_esc(span.get("byte_start"))}–{_esc(span.get("byte_end"))}</li>')
  rows.append(f'<li>{_esc(record.get("claim_id"))}: {_esc(record.get("text",claim.get("text")))}; uncertainty {_esc(c.get("uncertainty"))}; support {_esc(record.get("support_status"))}<ul>'+''.join(evidence)+'</ul></li>')
 return ''.join(rows)
def create_app(run_root,decision_root=None,explanation_path=None):
 s=load_sealed_run(run_root)
 if explanation_path is not None:
  from .governed_posture_explain import GovernedPostureExplanationError, load_atlas_explanation
  try:
   explanation,explanation_file_sha256,explanation_canonical_sha256=load_atlas_explanation(run_root,explanation_path)
  except GovernedPostureExplanationError as e:raise HumanReviewError(f'explanation is invalid: {e.code}') from e
  s['explanation']=explanation;s['explanation_bindings']={'atlas_explanation_packet_file_sha256':explanation_file_sha256,'atlas_explanation_packet_canonical_sha256':explanation_canonical_sha256}
 out=_decision_root(s,decision_root);csrf=secrets.token_urlsafe(32);pending=None;used=set();app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
 def reject(msg,status,code='REQUEST_REJECTED'):return _response(f'<h1 tabindex="-1">Request rejected</h1><p>{msg}</p><p>Reason code: {_esc(code)}</p>',status)
 def guard(req,form=None):
  host=_host(req.headers.get('host','')); client=req.client.host if req.client else None
  if not _loop(host):raise RequestRejected('REQUEST_HOST_NOT_LOOPBACK')
  if client is not None and not _loop_ip(client):raise RequestRejected('REQUEST_CLIENT_NOT_LOOPBACK')
  origin=req.headers.get('origin');site=req.headers.get('sec-fetch-site')
  if site == 'cross-site':raise RequestRejected('REQUEST_FETCH_SITE_CROSS_SITE')
  if site not in (None,'','none','same-origin','same-site'):raise RequestRejected('REQUEST_FETCH_SITE_INVALID')
  if origin not in (None,'','null',f'http://{req.headers.get("host")}'):raise RequestRejected('REQUEST_ORIGIN_MISMATCH')
  if form is not None:
   if not form.get('csrf'):raise RequestRejected('REQUEST_CSRF_MISSING')
   if not secrets.compare_digest(form['csrf'],csrf):raise RequestRejected('REQUEST_CSRF_INVALID')
 @app.middleware('http')
 async def boundary(req,call):
  try:
   if req.method=='POST':req.scope['_body']=await req.body()
   guard(req);return await call(req)
  except RequestRejected as e:return reject('The local request was not authorized.',403,e.code)
  except PermissionError:return reject('The local request was not authorized.',403)
  except HumanReviewError:return reject('The local review request could not be accepted.',409)
 def review(errors=(),values={}):
  c=s['candidate'];so=s['sophia'];a=s['atlas']; provider=a.get('provider_context'); provider_html='' if not provider else f'<h2>Provider execution context</h2><p>Provider: {_esc(provider["provider_id"])}; trust: {_esc(provider["trust_class"].replace("_", " "))}; data egress: {_esc(provider["data_egress"].replace("_", " "))}; adapter: {_esc(provider["adapter_id"])}; protocol: {_esc(provider["protocol"])}</p><p>Model requested: {_esc(provider["requested_model_id"])}; observed: {_esc(provider["observed_model_id"])}; identity assurance: {_esc(provider["assurance"])}. Provider and model identity establish execution provenance. They do not establish that the candidate is correct.</p>'; claims=_claims_html(s); findings=''.join(f'<li>{_esc(x)}</li>' for x in so.get('claim_findings',[])); err='' if not errors else '<div id="errors" tabindex="-1"><h2>Correct these fields</h2>'+''.join(f'<p>{_esc(x)}</p>' for x in errors)+'</div>'
  explanation_html=''
  if 'explanation' in s:
   e=s['explanation'];postures=e['posture_explanations']
   choices=''.join(f'<li><b>{_esc(key)}</b>: {_esc(value)}</li>' for key,value in e['decision_meanings'].items())
   posture_rows=''.join(f'<li><b>{_esc(key)}</b>: {_esc(value)}</li>' for key,value in postures.items())
   explanation_html=f'<h2>Why Sophia reached this disposition</h2><p>{_esc(e.get("sophia_disposition_explanation", "Sophia context was presented without truth certification."))}</p><h2>Why Atlas has this posture</h2><ul>{posture_rows}</ul><h2>What your choices mean</h2><ul>{choices}</ul>'
  return f'<h1>Local human review decision</h1>{err}<p>Run { _esc(s["request"]["run_id"]) } | logical time { _esc(s["request"]["logical_time"]) }</p><p>Question: {_esc(s["request"].get("question",s["request"].get("user_input")))}<br>Model provenance: {_esc(s["request"].get("model_id",s["request"].get("model","captured/provider-neutral")))}<br>Candidate: {_esc(c.get("answer"))}<br>Uncertainty: {_esc(c.get("uncertainty"))}</p><h2>Claims and citations</h2><ul>{claims}</ul><h2>Sophia</h2><p>{_esc(so.get("disposition"))}: {_esc(", ".join(so.get("reason_codes",[])))}</p><ul>{findings}</ul><h2>Atlas</h2><p>{_esc(a.get("retention_posture"))}; {_esc(a.get("publication_posture"))}; {_esc(a.get("expiry_posture"))}; {_esc(a.get("revocation_posture"))}; human decision PENDING</p>{provider_html}{explanation_html}<p><a href="/sealed-review">Open exact sealed review</a></p><form method="post" action="/review/preview"><input type="hidden" name="csrf" value="{_esc(csrf)}"><fieldset><legend>Decision (required)</legend><label><input required type="radio" name="decision" value="APPROVE"> APPROVE: accept bounded output.</label><label><input required type="radio" name="decision" value="HOLD"> HOLD: correction is required.</label><label><input required type="radio" name="decision" value="REJECT"> REJECT: output is not accepted.</label><label><input required type="radio" name="decision" value="REPAIR"> REPAIR: request a new bounded candidate lineage without changing this candidate.</label></fieldset><label for="reviewer">Reviewer display name (required)</label><input id="reviewer" name="reviewer" required aria-invalid="{"true" if "Reviewer" in " ".join(errors) else "false"}"><label for="note">Decision note (required for HOLD, REJECT, or REPAIR)</label><textarea id="note" name="note"></textarea><button>Preview decision</button></form>'
 @app.get('/review')
 async def get_review():
  if _existing(out,s['request']['run_id']):return _response('<h1 tabindex="-1">Decision already recorded</h1><p>This run is read-only.</p>',409)
  return _response(review())
 @app.get('/sealed-review')
 async def sealed():return HTMLResponse(s['files']['final_review.html'],headers=HEADERS)
 @app.post('/review/preview')
 async def preview(req:Request):
  nonlocal pending
  f=_form(req)
  try:guard(req,f)
  except RequestRejected as e:return reject('The local request was not authorized.',403,e.code)
  except PermissionError:return reject('The local request was not authorized.',403)
  d=f.get('decision','');errors=[]
  try:r=_reviewer_text(f.get('reviewer',''));n=_note_text(f.get('note',''))
  except HumanReviewError:r='';n='';errors.append('Reviewer or note is invalid.')
  if d not in DECISIONS:errors.append('Choose APPROVE, HOLD, REJECT, or REPAIR.')
  if not r:errors.append('Reviewer display name is required.')
  if d in NOTE_REQUIRED and not n:errors.append('A decision note is required for HOLD, REJECT, or REPAIR.')
  if errors:return _response(review(errors,f),400)
  token=secrets.token_urlsafe(32);pending={'token':token,'decision':d,'reviewer':r,'note':n,'run_id':s['request']['run_id'],'logical_time':s['request']['logical_time'],'evidence_bindings':s['hashes'],'explanation_evidence_bindings':s.get('explanation_bindings'),'sophia_disposition':s['sophia']['disposition'],'atlas_retention_posture':s['atlas'].get('retention_posture'),'atlas_publication_posture':s['atlas'].get('publication_posture'),'provider_evidence':s['atlas'].get('provider_context')}
  if s['atlas'].get('audit_id') and s['candidate'].get('candidate_id'):pending.update(audit_id=s['atlas']['audit_id'],candidate_id=s['candidate']['candidate_id'])
  if s.get('tel_finalization'):pending.update(decision_id=s['tel_finalization']['decision_id'])
  if d=='REPAIR':pending.update(repair_request_id=str(uuid.uuid4()),new_lineage_id=str(uuid.uuid4()))
  rows=''.join(f'<li>{_esc(k)}: {_esc(v)}</li>' for k,v in pending.items() if k!='token')
  return _response(f'<h1>Confirm decision</h1><ul>{rows}</ul><form method="post" action="/review/commit"><input type="hidden" name="csrf" value="{_esc(csrf)}"><input type="hidden" name="confirmation_token" value="{_esc(token)}"><button>Confirm decision</button></form>')
 @app.post('/review/commit')
 async def commit(req:Request):
  nonlocal pending
  f=_form(req)
  try:guard(req,f)
  except RequestRejected as e:return reject('The local request was not authorized.',403,e.code)
  except PermissionError:return reject('The local request was not authorized.',403)
  token=f.get('confirmation_token','')
  if not pending or token in used or not secrets.compare_digest(token,pending.get('token','')):return reject('The decision confirmation conflicts with this session.',409)
  record=pending;pending=None;used.add(token)
  published=None
  try:
   if _existing(out,record['run_id']):return reject('A decision already exists for this run.',409)
   if not _unchanged(s['root'],s['files']):raise HumanReviewError
   did=record.get('decision_id') or str(uuid.uuid4());generated=datetime.now(timezone.utc).isoformat();repair_data=None;repair_binding=None
   if record['decision']=='REPAIR':
    repair_packet={'schema_id':'uvlm.bounded_repair_request.v1','schema_version':'1.0','packet_type':'bounded_repair_request','repair_request_id':record['repair_request_id'],'decision_id':did,'decision':'REPAIR','generated_at_utc':generated,'reviewer':{'display_name':record['reviewer'],'identity_assurance':'local_assertion_only','cryptographic_signature_present':False},'repair_note':record['note'],'parent_run':{'run_id':record['run_id'],'logical_time':record['logical_time'],'run_manifest_path':'run_manifest.json','run_manifest_file_sha256':record['evidence_bindings']['run_manifest.json']},'parent_candidate':{'path':'candidate_packet.json','file_sha256':record['evidence_bindings']['candidate_packet.json']},'new_lineage_id':record['new_lineage_id'],'route':{'owner':'Sonya','status':'REQUESTED_NOT_EXECUTED','requires_new_governed_run':True,'requires_full_human_review':True,'candidate_generation_performed':False,'candidate_revision_performed':False},'candidate_content_included':False,'authority_boundary':dict.fromkeys(REPAIR_AUTH,False),'side_effects':dict.fromkeys(REPAIR_EFFECTS,False),'nonauthority':'This artifact records a bounded Sonya-routed repair request and establishes a child lineage identifier only. It does not execute repair, generate or revise candidate content, or grant authority.'}
    repair_data=_canon(repair_packet)+b'\n';repair_binding={'artifact_type':'bounded_repair_request','path':'repair_request.json','file_sha256':_sha(repair_data),'canonical_sha256':_sha(_canon(repair_packet)),'repair_request_id':record['repair_request_id'],'new_lineage_id':record['new_lineage_id']}
   packet={'schema_id':'uvlm.human_review_decision.v1','schema_version':'1.0','packet_type':'human_review_decision','decision_id':did,'run_id':record['run_id'],'logical_time':record['logical_time'],**({'audit_id':record['audit_id'],'candidate_id':record['candidate_id']} if record.get('audit_id') and record.get('candidate_id') else {}),'generated_at_utc':generated,'reviewer':{'display_name':record['reviewer'],'identity_assurance':'local_assertion_only','cryptographic_signature_present':False},'decision':record['decision'],'decision_note':record['note'],'source':{'interface':'atlas_local_human_review_ui','loopback_only':True},'evidence_bindings':record['evidence_bindings'],**({'explanation_evidence_bindings':record['explanation_evidence_bindings']} if record['explanation_evidence_bindings'] else {}),**({'repair_request_binding':repair_binding} if repair_binding else {}),'sophia_disposition':record['sophia_disposition'],'atlas_retention_posture':record['atlas_retention_posture'],'atlas_publication_posture':record['atlas_publication_posture'],**({'provider_evidence':record['provider_evidence']} if record['provider_evidence'] else {}),'requires_human_review':True,'authority_boundary':dict.fromkeys(AUTH,False),'side_effects':dict.fromkeys(EFFECTS,False),'nonauthority':'This receipt records a bounded human decision only.'};data=_canon(packet)+b'\n';tel_data=None
   if s.get('tel_rows'):
    parent=s['files']['tel_events.jsonl'];event={'schema_id':'uvlm.coherence.totality.tel_event.v1','sequence':19,'logical_time':'T+000019','event_type':'HUMAN_DECISION_RECORDED','run_id':record['run_id'],'candidate_id':record['candidate_id'],'audit_id':record['audit_id'],'decision_id':did,'outcome':'RECORDED','payload':{'decision_receipt_sha256':_sha(data),'disposition':record['decision'],'external_receipt_path':'human_review_decision.json','parent_sealed_tel_sha256':_sha(parent)},'authority_effect':'NONE'};tel_data=parent+_canon(event)+b'\n'
   with TemporaryDirectory(dir=out,prefix='.pending-') as temp:
    t=Path(temp);(t/'human_review_decision.json').write_bytes(data);(t/'human_review_decision.json.sha256').write_bytes(f'{_sha(data)}  human_review_decision.json\n'.encode('ascii'))
    if tel_data is not None:
     (t/'tel_human_continuation.jsonl').write_bytes(tel_data);(t/'tel_human_continuation.jsonl.sha256').write_bytes(f'{_sha(tel_data)}  tel_human_continuation.jsonl\n'.encode('ascii'))
    repair_html=''
    if repair_data is not None:
     (t/'repair_request.json').write_bytes(repair_data);(t/'repair_request.json.sha256').write_bytes(f'{_sha(repair_data)}  repair_request.json\n'.encode('ascii'));repair_html=f'<p>Bounded repair request: {_esc(record["repair_request_id"])}; new lineage: {_esc(record["new_lineage_id"])}; route: Sonya requested, not executed. No candidate content was generated or revised.</p>'
    bindings=''.join(f'<li>{_esc(k)}: {_esc(v)}</li>' for k,v in record['evidence_bindings'].items());(t/'human_review_decision_receipt.html').write_text(f'<!doctype html><html><body><h1>Human decision receipt</h1><p>This receipt records a human decision. It does not certify truth. It does not authorize memory or PMR write, canonization or publication, DOI, Crossref, catalog, or graph mutation, deployment, release, or automatic phase advance.</p><p>ID: {_esc(did)}; decision: {_esc(record["decision"])}; reviewer: {_esc(record["reviewer"])}; note: {_esc(record["note"])}; run: {_esc(record["run_id"])}; logical time: {_esc(record["logical_time"])}; timestamp: {_esc(packet["generated_at_utc"])}</p><p>Sophia: {_esc(record["sophia_disposition"])}; Atlas: {_esc(record["atlas_retention_posture"])} / {_esc(record["atlas_publication_posture"])}; identity assurance local_assertion_only; cryptographic signature absent.</p>{repair_html}<ul>{bindings}</ul></body></html>',encoding='utf-8');published=out/did;os.replace(t,published)
   if not _unchanged(s['root'],s['files']):raise HumanReviewError
  except HumanReviewError:
   if published is not None and published.is_dir() and published.parent==out:
    rollback=out/f'.rollback-{uuid.uuid4().hex}'
    try:os.replace(published,rollback);shutil.rmtree(rollback)
    except OSError:return reject('The sealed review transaction conflicts and requires bounded cleanup.',409)
   return reject('The sealed review transaction conflicts.',409)
  return _response('<h1 tabindex="-1">Decision recorded</h1><p>The immutable bounded decision receipt was written outside the sealed run root.</p>')
 return app
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-root',required=True);p.add_argument('--decision-root');p.add_argument('--explanation-path');p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8765);p.add_argument('--no-browser',action='store_true');a=p.parse_args()
 if not _loop(a.host):raise SystemExit('host must resolve only to loopback')
 if not a.no_browser:webbrowser.open(f'http://{a.host}:{a.port}/review')
 uvicorn.run(create_app(a.run_root,a.decision_root,a.explanation_path),host=a.host,port=a.port)
if __name__=='__main__':main()
