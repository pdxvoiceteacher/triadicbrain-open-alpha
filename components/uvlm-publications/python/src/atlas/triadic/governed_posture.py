"""Deterministic, file-only Atlas posture and human-review renderer."""
from __future__ import annotations
import argparse, hashlib, html, json, os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

class GovernedPostureError(ValueError): pass
SHA = "0123456789abcdef"
SOPHIA_NONAUTH = ("truth_certification","final_answer_authority","memory_write_authority","canonization","publication","deployment","model_invocation","candidate_alteration","external_action_authority")
SOPHIA_EFFECTS = ("network_access_performed","model_invocation_performed","candidate_mutation_performed","source_mutation_performed","memory_write_performed","canonization_performed","publication_performed","deployment_performed","pmr_write_performed")
ATLAS_NONAUTH = ("truth_certification","final_answer_authority","memory_write_authority","pmr_write_authority","canonization","publication","doi_mutation","crossref_deposit","catalog_mutation","knowledge_graph_mutation","deployment","release","model_invocation","candidate_alteration","sophia_alteration","external_action_authority")
ATLAS_EFFECTS = ("network_access_performed","model_invocation_performed","candidate_mutation_performed","sophia_mutation_performed","source_mutation_performed","memory_write_performed","pmr_write_performed","canonization_performed","publication_performed","doi_mutated","crossref_deposit_performed","catalog_mutated","knowledge_graph_mutated","deployment_performed","release_performed")
FORBIDDEN = ("chain_of_thought","private_reasoning","hidden_reasoning","scratchpad","internal_deliberation","thinking","raw_output","raw_model_output","prompt_text","source_prompt","self_approval")
POSITIVE = ("truth_certified","final_answer_authorized","memory_write_authorized","canonization_authorized","publication_authorized","deployment_authorized","self_approved","governance_approved","release_authorized","doi_authorized","crossref_authorized")

def _constant(value: str) -> Any: raise ValueError("non-finite JSON number")
def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = {}
    for k,v in pairs:
        if k in out: raise ValueError("duplicate JSON member")
        out[k]=v
    return out
def _canon(value: Any) -> bytes: return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
def _hash(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _load(path: Path) -> tuple[dict[str,Any],str,str]:
    try: raw=path.read_bytes()
    except OSError as e: raise GovernedPostureError("required artifact unavailable") from e
    if b"\0" in raw: raise GovernedPostureError("invalid JSON contract")
    try: value=json.loads(raw.decode("utf-8"),object_pairs_hook=_pairs,parse_constant=_constant)
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as e: raise GovernedPostureError("invalid JSON contract") from e
    if not isinstance(value,dict): raise GovernedPostureError("JSON top-level must be object")
    return value,_hash(raw),_hash(_canon(value))
def _below(root: Path, path: Path) -> None:
    if path.is_symlink() or not path.is_file(): raise GovernedPostureError("unsafe or missing required artifact")
    try: path.resolve().relative_to(root)
    except ValueError as e: raise GovernedPostureError("artifact outside run root") from e
def _need(obj:dict[str,Any], keys:tuple[str,...], label:str) -> None:
    if any(k not in obj for k in keys): raise GovernedPostureError(f"{label} contract missing required field")
def _string(v:Any) -> bool: return isinstance(v,str) and bool(v)
def _sha(v:Any) -> bool: return isinstance(v,str) and len(v)==64 and all(x in SHA for x in v)
def _scan(v:Any,key:str="") -> None:
    k=key.lower()
    if k in FORBIDDEN or (k.startswith("raw_output") and k!="raw_output_sha256"): raise GovernedPostureError("prohibited private or raw material")
    if k in POSITIVE and v is True: raise GovernedPostureError("positive authority prohibited")
    if isinstance(v,dict):
        for a,b in v.items(): _scan(b,a)
    elif isinstance(v,list):
        for a in v: _scan(a,key)
def _exact(value:Any, expected:Any, label:str) -> None:
    if value != expected: raise GovernedPostureError(f"{label} contract mismatch")
def _parent(typ:str,path:str,file_digest:str,canon_digest:str|None=None) -> dict[str,str]:
    out={"artifact_type":typ,"path":path}
    if canon_digest is None: out["sha256"]=file_digest
    else: out.update(file_sha256=file_digest,canonical_sha256=canon_digest)
    return out
def _esc(v:Any) -> str: return html.escape(str(v))
def _rows(items:list[Any], fields:tuple[str,...]) -> str:
    return "".join("<li>"+ " | ".join(f"<b>{_esc(k)}</b>: {_esc(x.get(k,''))}" for k in fields) +"</li>" for x in items if isinstance(x,dict))

def _html(req:dict[str,Any], man:dict[str,Any], cand:dict[str,Any], sop:dict[str,Any], post:dict[str,Any]) -> bytes:
    claims=_rows(cand["claims"],("claim_id","text","uncertainty","support_status","candidate_maturity"))
    citations=[]
    for c in cand["claims"]:
        if isinstance(c,dict): citations.extend(c.get("citations",[]) if isinstance(c.get("citations",[]),list) else [])
    cites=_rows(citations,("segment_id","segment_sha256","source_ordinal","exact_excerpt"))
    findings=_rows(sop["claim_findings"],("claim_id","evidence_status","maturity_status","uncertainty_status"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Atlas human review</title></head><body>
<h1>Atlas governed human review</h1><p>Run: {_esc(post["run_id"])} | logical time: {_esc(post["logical_time"])}</p>
<h2>Request</h2><p>Question: {_esc(req["question"])} | selected model: {_esc(req["model_id"])}</p>
<h2>Grounding</h2><p>{_esc(man["source_id"])} | {_esc(man["source_label"])} | {_esc(man["source_sha256"])} | {_esc(man["normalized_sha256"])} | {_esc(man["media_type"])}</p>
<h2>Candidate</h2><p>{_esc(cand["answer"])} | uncertainty: {_esc(cand["uncertainty"])}</p><p>provider: {_esc(cand["provider"].get("provider_id") if isinstance(cand["provider"],dict) else cand["provider"])}; requested: {_esc(cand.get("model_identity",{}).get("requested_model_id") if isinstance(cand.get("model_identity"),dict) else cand.get("requested_model_id"))}; observed: {_esc(cand.get("model_identity",{}).get("observed_model_id") if isinstance(cand.get("model_identity"),dict) else cand.get("observed_response_model"))}; replay: {_esc(cand["replay_mode"])}</p>
<h3>Claims</h3><ul>{claims}</ul><h3>Citations</h3><ul>{cites}</ul>
<h2>Sophia</h2><p>{_esc(sop["disposition"])} | reason codes: {_esc(", ".join(sorted(sop["reason_codes"]))) } | authority: {_esc(sop["authority_boundary_status"])}</p><ul>{findings}</ul>
<h2>Atlas</h2><p>{_esc(post["retention_posture"])} | {_esc(post["publication_posture"])} | {_esc(post["expiry_posture"])} | {_esc(post["revocation_posture"])} | human review: true | human decision: PENDING</p>
<p>Candidate is not final. Sophia disposition is not truth certification. Atlas posture is not memory write or canonization and is not publication authorization. No DOI, Crossref, catalog, graph, deployment, or release action occurred. Human final authority remains binding.</p></body></html>""".encode("utf-8")

def assign_governed_posture(run_root: str|Path) -> dict[str,Any]:
    original=Path(run_root)
    if not original.is_absolute() or original == Path(original.anchor): raise GovernedPostureError("run_root must be non-root absolute directory")
    root=original.resolve()
    if not root.is_dir(): raise GovernedPostureError("run_root must be existing directory")
    paths={"request":root/"request.json","manifest":root/"grounding/manifest.json","segments":root/"grounding/segments.jsonl","candidate":root/"candidate_packet.json","sophia":root/"sophia_audit_packet.json"}
    for p in paths.values(): _below(root,p)
    req,rf,rc=_load(paths["request"]); man,mf,mc=_load(paths["manifest"]); cand,cf,cc=_load(paths["candidate"]); sop,sf,sc=_load(paths["sophia"])
    for obj in (req,man,cand,sop): _scan(obj)
    _need(req,("schema_id","run_id","logical_time","question","model_id","replay_mode","producer_repository"),"request")
    request_version={"uvlm.coherencelattice.request.v1":1,"uvlm.coherencelattice.request.v2":2}.get(req["schema_id"])
    if request_version is None: raise GovernedPostureError("request contract mismatch")
    _exact(req["producer_repository"],"pdxvoiceteacher/CoherenceLattice","request")
    if not all(_string(req[k]) for k in ("run_id","logical_time","question","model_id")) or not isinstance(req["replay_mode"],bool): raise GovernedPostureError("request contract invalid")
    _need(man,("schema","source_id","source_label","source_sha256","normalized_sha256","media_type","artifacts","run_id","logical_time","producer_repository"),"manifest")
    _exact(man["schema"],"coherencelattice.grounding_bundle.v1","manifest"); _exact(man["producer_repository"],"pdxvoiceteacher/CoherenceLattice","manifest"); _exact(man["artifacts"],{"source_md":"source.md","segments_jsonl":"segments.jsonl","conversion_report_json":"conversion_report.json"},"manifest")
    if not all(_string(man[k]) for k in ("source_id","source_label","media_type","run_id","logical_time")) or not _sha(man["source_sha256"]) or not _sha(man["normalized_sha256"]): raise GovernedPostureError("manifest contract invalid")
    ck=("schema_id","schema_version","packet_type","producer_repository","producer","run_id","logical_time","parents","request_sha256","grounding_manifest_sha256","source_sha256","normalized_source_sha256","sonya_request_id","sonya_candidate_id","sonya_node_id","provider","requested_model_id","observed_response_model","installed_model_digest","adapter_identity","raw_output_sha256","completion","real_model_invoked","replay_mode","answer","uncertainty","claims","candidate_not_final","not_truth_certification","not_governance_approval","not_memory_authorization","not_publication_authorization","not_deployment_authority","human_review_required")
    v2 = cand.get("schema_id") == "uvlm.coherencelattice.candidate_packet.v2"
    if v2:
        v2k=tuple(x for x in ck if x not in ("provider","requested_model_id","observed_response_model","installed_model_digest","adapter_identity","completion","real_model_invoked"))+ ("model_identity","completion")
        _need(cand,v2k,"candidate"); _exact(cand["schema_version"],"2.0","candidate")
    else:
        _need(cand,ck,"candidate"); _exact(cand["schema_id"],"uvlm.coherencelattice.candidate_packet.v1","candidate"); _exact(cand["schema_version"],"v1","candidate")
    if request_version != (2 if v2 else 1): raise GovernedPostureError("request/candidate version pair mismatch")
    _exact(cand["packet_type"],"candidate_packet","candidate"); _exact(cand["producer_repository"],"pdxvoiceteacher/CoherenceLattice","candidate"); _exact(cand["producer"],{"repository":"CoherenceLattice","role":"candidate_canonicalizer"},"candidate")
    if not all(cand[x] is True for x in ("candidate_not_final","not_truth_certification","not_governance_approval","not_memory_authorization","not_publication_authorization","not_deployment_authority","human_review_required")): raise GovernedPostureError("candidate nonauthority invalid")
    provider_context=None
    if v2:
        provider=cand["provider"]; identity=cand["model_identity"]; completion=cand["completion"]
        if not isinstance(provider,dict) or set(provider)!={"provider_id","adapter_id","adapter_version","protocol","trust_class","data_egress","profile_sha256","endpoint_sha256"}: raise GovernedPostureError("candidate v2 provider invalid")
        if not all(_string(provider[k]) for k in ("provider_id","adapter_id","adapter_version","protocol")) or provider["trust_class"] not in ("local_loopback","private_network","external_managed") or provider["data_egress"] not in ("none","private_network","external") or not _sha(provider["profile_sha256"]) or not _sha(provider["endpoint_sha256"]): raise GovernedPostureError("candidate v2 provider invalid")
        if not isinstance(identity,dict) or set(identity)!={"requested_model_id","observed_model_id","assurance","artifact_digest_sha256","provider_model_version"} or not _string(identity["requested_model_id"]) or not _string(identity["observed_model_id"]) or identity["assurance"] not in ("artifact_digest_verified","provider_version_reported","requested_and_observed_id_only"): raise GovernedPostureError("candidate v2 identity invalid")
        if identity["assurance"]=="artifact_digest_verified" and not _sha(identity["artifact_digest_sha256"]): raise GovernedPostureError("candidate v2 identity invalid")
        if identity["assurance"]!="artifact_digest_verified" and identity["artifact_digest_sha256"] is not None: raise GovernedPostureError("candidate v2 identity invalid")
        if identity["assurance"]=="provider_version_reported" and not _string(identity["provider_model_version"]): raise GovernedPostureError("candidate v2 identity invalid")
        if identity["assurance"]!="provider_version_reported" and identity["provider_model_version"] is not None: raise GovernedPostureError("candidate v2 identity invalid")
        if not isinstance(completion,dict) or completion.get("complete") is not True or not isinstance(completion.get("finish_reason"),str) or any(completion.get(k) is not None and (not isinstance(completion[k],int) or completion[k]<0) for k in ("input_tokens","output_tokens","time_to_first_byte_ms","total_duration_ms")) or completion.get("provider_request_id_sha256") is not None: raise GovernedPostureError("candidate v2 completion invalid")
        for key in ("provider_id","provider_profile_sha256","provider_trust_class","data_egress","external_provider_consent"):
            if key not in req: raise GovernedPostureError("v2 request invalid")
        if not _string(req["provider_id"]) or not _sha(req["provider_profile_sha256"]) or req["provider_trust_class"] not in ("local_loopback","private_network","external_managed") or req["data_egress"] not in ("none","private_network","external") or not isinstance(req["external_provider_consent"],bool): raise GovernedPostureError("v2 request invalid")
        if req["provider_id"]!=provider["provider_id"] or req["provider_profile_sha256"]!=provider["profile_sha256"] or req["provider_trust_class"]!=provider["trust_class"] or req["data_egress"]!=provider["data_egress"] or req["model_id"]!=identity["requested_model_id"] or (provider["data_egress"]!="none" and req["external_provider_consent"] is not True): raise GovernedPostureError("v2 request/provider mismatch")
        provider_context={**provider,**identity}
    sk=("schema_id","schema_version","packet_type","producer_repository","producer","run_id","logical_time","request_file_sha256","request_canonical_sha256","grounding_manifest_sha256","grounding_manifest_canonical_sha256","candidate_sha256","candidate_canonical_sha256","parent_list","disposition","reason_codes","claim_findings","authority_boundary_status","requires_human_review","permitted_next_route","nonauthority","side_effects")
    _need(sop,sk,"Sophia"); _exact(sop["schema_id"],"uvlm.sophia.audit_packet.v1","Sophia"); _exact(sop["schema_version"],"1.1","Sophia"); _exact(sop["packet_type"],"sophia_audit_packet","Sophia"); _exact(sop["producer_repository"],"pdxvoiceteacher/Sophia","Sophia"); _exact(sop["producer"],{"repository":"pdxvoiceteacher/Sophia","role":"independent_candidate_auditor","version":"1.1"},"Sophia")
    if sop["disposition"] not in ("PASS","HOLD","REJECT") or not sop["requires_human_review"] or not isinstance(sop["reason_codes"],list) or not all(isinstance(x,str) for x in sop["reason_codes"]) or not isinstance(sop["claim_findings"],list): raise GovernedPostureError("Sophia contract invalid")
    _exact(sop["permitted_next_route"],"none" if sop["disposition"]=="REJECT" else "atlas_posture_only","Sophia route")
    for key in SOPHIA_NONAUTH+SOPHIA_EFFECTS:
        group=sop["nonauthority"] if key in SOPHIA_NONAUTH else sop["side_effects"]
        if not isinstance(group,dict) or group.get(key) is not False: raise GovernedPostureError("Sophia authority ceiling invalid")
    if any(x["run_id"]!=req["run_id"] or x["logical_time"]!=req["logical_time"] for x in (man,cand,sop)): raise GovernedPostureError("cross-packet identity mismatch")
    _exact(cand["request_sha256"],rc,"candidate request digest"); _exact(cand["grounding_manifest_sha256"],mc,"candidate manifest digest")
    _exact(cand["parents"],[_parent("request","request.json",rc),_parent("grounding_manifest","grounding/manifest.json",mc)],"candidate parents"); _exact(cand["source_sha256"],man["source_sha256"],"candidate source"); _exact(cand["normalized_source_sha256"],man["normalized_sha256"],"candidate source")
    for k,v in (("request_file_sha256",rf),("request_canonical_sha256",rc),("grounding_manifest_sha256",mf),("grounding_manifest_canonical_sha256",mc),("candidate_sha256",cf),("candidate_canonical_sha256",cc)): _exact(sop[k],v,"Sophia digest")
    _exact(sop["parent_list"],[_parent("request","request.json",rf,rc),_parent("grounding_manifest","grounding/manifest.json",mf,mc),_parent("candidate_packet","candidate_packet.json",cf,cc)],"Sophia parents")
    retention,publication={"PASS":("retain_for_human_review","publication_blocked_pending_human_review"),"HOLD":("quarantine","do_not_publish"),"REJECT":("rejected","do_not_publish")}[sop["disposition"]]
    parents=[_parent("request","request.json",rf,rc),_parent("grounding_manifest","grounding/manifest.json",mf,mc),_parent("candidate_packet","candidate_packet.json",cf,cc),_parent("sophia_audit_packet","sophia_audit_packet.json",sf,sc)]
    post={"schema_id":"uvlm.atlas.posture_packet.v1","schema_version":"1.1","packet_type":"atlas_posture_packet","run_id":req["run_id"],"logical_time":req["logical_time"],"producer_repository":"pdxvoiceteacher/uvlm-publications","producer":{"repository":"pdxvoiceteacher/uvlm-publications","role":"bounded_posture_and_human_review_renderer","version":"1.1"},"request_file_sha256":rf,"request_canonical_sha256":rc,"grounding_manifest_sha256":mf,"grounding_manifest_canonical_sha256":mc,"candidate_sha256":cf,"candidate_canonical_sha256":cc,"sophia_packet_sha256":sf,"sophia_packet_canonical_sha256":sc,"parent_list":parents,"source_id":man["source_id"],"source_label":man["source_label"],"source_sha256":man["source_sha256"],"normalized_source_sha256":man["normalized_sha256"],"sophia_disposition":sop["disposition"],"sophia_reason_codes":sorted(sop["reason_codes"]),"sophia_claim_findings":sop["claim_findings"],"sophia_authority_boundary_status":sop["authority_boundary_status"],"provider_context":provider_context,"retention_posture":retention,"publication_posture":publication,"expiry_posture":"review_bounded","revocation_posture":"revocable","requires_human_review":True,"human_decision":"PENDING","nonauthority":dict.fromkeys(ATLAS_NONAUTH,False),"side_effects":dict.fromkeys(ATLAS_EFFECTS,False)}
    for path,data in ((root/"atlas_posture_packet.json",_canon(post)+b"\n"),(root/"final_review.html",_html(req,man,cand,sop,post))):
        with NamedTemporaryFile(dir=root,delete=False) as f: f.write(data); tmp=f.name
        os.replace(tmp,path)
    return post
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--run-root",required=True); assign_governed_posture(p.parse_args().run_root); return 0
if __name__=="__main__": raise SystemExit(main())
