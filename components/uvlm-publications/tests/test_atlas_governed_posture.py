from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"python"/"src"))
from atlas.triadic.governed_posture import GovernedPostureError,assign_governed_posture
def canonical(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,sort_keys=True)+"\n"); return hashlib.sha256(p.read_bytes()).hexdigest()
def run(root,disposition="PASS"):
 rid,t="r1","t1"; (root/"grounding").mkdir(parents=True); (root/"grounding/segments.jsonl").write_text("{}\n")
 req={"schema_id":"uvlm.coherencelattice.request.v1","run_id":rid,"logical_time":t,"question":"<question>","model_id":"opaque/backend","replay_mode":True,"producer_repository":"pdxvoiceteacher/CoherenceLattice"}
 rf=write(root/"request.json",req); rc=canonical(req)
 man={"schema":"coherencelattice.grounding_bundle.v1","source_id":"s","source_label":"label","source_sha256":"a"*64,"normalized_sha256":"b"*64,"media_type":"text/plain","artifacts":{"source_md":"source.md","segments_jsonl":"segments.jsonl","conversion_report_json":"conversion_report.json"},"run_id":rid,"logical_time":t,"producer_repository":"pdxvoiceteacher/CoherenceLattice"}
 mf=write(root/"grounding/manifest.json",man); mc=canonical(man)
 cand={"schema_id":"uvlm.coherencelattice.candidate_packet.v1","schema_version":"v1","packet_type":"candidate_packet","producer_repository":"pdxvoiceteacher/CoherenceLattice","producer":{"repository":"CoherenceLattice","role":"candidate_canonicalizer"},"run_id":rid,"logical_time":t,"parents":[{"artifact_type":"request","path":"request.json","sha256":rc},{"artifact_type":"grounding_manifest","path":"grounding/manifest.json","sha256":mc}],"request_sha256":rc,"grounding_manifest_sha256":mc,"source_sha256":"a"*64,"normalized_source_sha256":"b"*64,"sonya_request_id":"x","sonya_candidate_id":"y","sonya_node_id":"z","provider":"opaque","requested_model_id":"opaque/backend","observed_response_model":"returned","installed_model_digest":"d","adapter_identity":"adapter","raw_output_sha256":"c"*64,"completion":"done","real_model_invoked":False,"replay_mode":True,"answer":"answer","uncertainty":"partial","claims":[{"claim_id":"c1","text":"claim","uncertainty":"partial","support_status":"supported","candidate_maturity":"draft","citations":[{"segment_id":"seg","segment_sha256":"d","source_ordinal":1,"exact_excerpt":"excerpt"}]}],"candidate_not_final":True,"not_truth_certification":True,"not_governance_approval":True,"not_memory_authorization":True,"not_publication_authorization":True,"not_deployment_authority":True,"human_review_required":True}
 cf=write(root/"candidate_packet.json",cand); cc=canonical(cand)
 non={k:False for k in ("truth_certification","final_answer_authority","memory_write_authority","canonization","publication","deployment","model_invocation","candidate_alteration","external_action_authority")}; effects={k:False for k in ("network_access_performed","model_invocation_performed","candidate_mutation_performed","source_mutation_performed","memory_write_performed","canonization_performed","publication_performed","deployment_performed","pmr_write_performed")}
 sop={"schema_id":"uvlm.sophia.audit_packet.v1","schema_version":"1.1","packet_type":"sophia_audit_packet","producer_repository":"pdxvoiceteacher/Sophia","producer":{"repository":"pdxvoiceteacher/Sophia","role":"independent_candidate_auditor","version":"1.1"},"run_id":rid,"logical_time":t,"request_file_sha256":rf,"request_canonical_sha256":rc,"grounding_manifest_sha256":mf,"grounding_manifest_canonical_sha256":mc,"candidate_sha256":cf,"candidate_canonical_sha256":cc,"parent_list":[{"artifact_type":"request","path":"request.json","file_sha256":rf,"canonical_sha256":rc},{"artifact_type":"grounding_manifest","path":"grounding/manifest.json","file_sha256":mf,"canonical_sha256":mc},{"artifact_type":"candidate_packet","path":"candidate_packet.json","file_sha256":cf,"canonical_sha256":cc}],"disposition":disposition,"reason_codes":["z","a"],"claim_findings":[{"claim_id":"c1","evidence_status":"supported","maturity_status":"draft","uncertainty_status":"partial"}],"authority_boundary_status":"bounded","requires_human_review":True,"permitted_next_route":"none" if disposition=="REJECT" else "atlas_posture_only","nonauthority":non,"side_effects":effects}
 write(root/"sophia_audit_packet.json",sop); return root
@pytest.mark.parametrize("d,expected",[("PASS",("retain_for_human_review","publication_blocked_pending_human_review")),("HOLD",("quarantine","do_not_publish")),("REJECT",("rejected","do_not_publish"))])
def test_current_contract_and_rendering(tmp_path,d,expected):
 r=run(tmp_path,d); before={p:p.read_bytes() for p in (r/"request.json",r/"grounding/manifest.json",r/"candidate_packet.json",r/"sophia_audit_packet.json")}; p=assign_governed_posture(r)
 assert (p["retention_posture"],p["publication_posture"])==expected and p["grounding_manifest_sha256"]!=p["grounding_manifest_canonical_sha256"]
 h=(r/"final_review.html").read_text(); assert "claim" in h and "excerpt" in h and "&lt;question&gt;" in h
 first=(r/"atlas_posture_packet.json").read_bytes(),(r/"final_review.html").read_bytes(); assign_governed_posture(r); assert first==((r/"atlas_posture_packet.json").read_bytes(),(r/"final_review.html").read_bytes()) and before=={p:p.read_bytes() for p in before}
@pytest.mark.parametrize("mutate",[lambda r:(r/"sophia_audit_packet.json").unlink(),lambda r:(r/"request.json").write_bytes(b'{"x":1,"x":2}'),lambda r:(r/"candidate_packet.json").write_bytes(b'{"x":NaN}'),lambda r:(r/"candidate_packet.json").write_bytes(b'\0')])
def test_malformed_and_missing_fail_closed(tmp_path,mutate):
 r=run(tmp_path); mutate(r)
 with pytest.raises(GovernedPostureError): assign_governed_posture(r)
def test_relative_root_rejected(tmp_path):
 with pytest.raises(GovernedPostureError): assign_governed_posture(".")
def test_candidate_v1_request_v2_pair_rejected(tmp_path):
 r=run(tmp_path);req=json.loads((r/"request.json").read_text());req["schema_id"]="uvlm.coherencelattice.request.v2";write(r/"request.json",req)
 with pytest.raises(GovernedPostureError,match="request/candidate version pair mismatch"):assign_governed_posture(r)
def test_authority_and_side_effect_denials_remain_false(tmp_path):
 p=assign_governed_posture(run(tmp_path))
 assert p["requires_human_review"] is True and p["human_decision"]=="PENDING"
 assert p["nonauthority"] and all(value is False for value in p["nonauthority"].values())
 assert p["side_effects"] and all(value is False for value in p["side_effects"].values())
def test_request_file_and_canonical_hash_tampering_rejected(tmp_path):
 r=run(tmp_path);(r/"request.json").write_text((r/"request.json").read_text()+"\n")
 with pytest.raises(GovernedPostureError,match="Sophia digest"):assign_governed_posture(r)
 r=run(tmp_path/"canonical");s=json.loads((r/"sophia_audit_packet.json").read_text());s["request_canonical_sha256"]="0"*64;write(r/"sophia_audit_packet.json",s)
 with pytest.raises(GovernedPostureError,match="Sophia digest"):assign_governed_posture(r)
