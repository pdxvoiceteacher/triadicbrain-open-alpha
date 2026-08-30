"""Server-rendered, loopback-only AHA source-to-review pages."""
from __future__ import annotations

import secrets
from html import escape
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .models import CaseValidationError
from .workflow import build_case, intake, read_inventory, run_review, session_root

MAX_SOURCE = 2 * 1024 * 1024
MAX_UPLOAD = 8 * 1024 * 1024


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{escape(title)}</title></head><body><header><p>Sources → Structure → Review</p></header>{body}</body></html>")


def _error(code: str, status: int = 400, detail: str = "Please correct the labelled field and try again.") -> HTMLResponse:
    return _page("AHA review error", f"<h1>AHA Pattern Donation review</h1><h2 tabindex='-1'> {escape(code)}</h2><p>{escape(detail)}</p>").__class__(f"<!doctype html><html><body><h1>AHA Pattern Donation review</h1><h2 tabindex='-1'>{escape(code)}</h2><p>{escape(detail)}</p></body></html>", status_code=status)


def _source_form(error: str = "") -> HTMLResponse:
    note = f"<h2 tabindex='-1'> {escape(error)}</h2>" if error else ""
    return _page("AHA source intake", f"<h1>AHA Pattern Donation review</h1><p>Upload one target source and two to five donor sources. You will describe the bridge in the next step; no hashes or JSON are required.</p>{note}<form method='post' action='/aha/intake' enctype='multipart/form-data'><input type='hidden' name='csrf_token' value='{{csrf}}'><fieldset><legend>Target source</legend><label>File <input required type='file' name='target_file' accept='.txt,.md'></label><label>Source label <input required name='target_label'></label><label>Domain <input required name='target_domain'></label><label>Source family ID <input required name='target_family'></label></fieldset><fieldset><legend>Donor sources (two to five)</legend><p>Provide one row for each donor.</p><label>Files <input required type='file' name='donor_files' multiple accept='.txt,.md'></label><label>Labels, one per line <textarea required name='donor_labels'></textarea></label><label>Domains, one per line <textarea required name='donor_domains'></textarea></label><label>Source family IDs, one per line <textarea required name='donor_families'></textarea></label></fieldset><button type='submit'>Build source inventory</button></form>")


def _construct(inventory: list[dict], session_id: str, error: str = "") -> HTMLResponse:
    segments = "".join(f"<li><strong>{escape(seg['segment_id'])}</strong>: {escape(seg['text'][:500])}</li>" for source in inventory for seg in source["segments"])
    sources = ", ".join(f"{escape(s['source_id'])} ({escape(s['domain'])})" for s in inventory)
    error_html = f"<h2 tabindex='-1'>{escape(error)}</h2>" if error else ""
    fields = "".join(f"<label>{escape(label.replace('_', ' '))} <input required name='{label}'></label>" for label in ("case_id", "question", "statement", "target_observable", "intervention_or_condition", "expected_direction", "comparator_or_null", "horizon", "confidence_lowering_observation", "test_statement", "primary_outcome", "comparator", "reject_criteria", "feasibility_posture", "risk_posture"))
    return _page("AHA guided construction", f"<h1>AHA Pattern Donation review</h1><p>Describe only the structures you intend to review. Each line uses the visible pipe-separated format; references appear beside excerpts below.</p>{error_html}<h2>Source inventory</h2><p>{sources}</p><h2>Available evidence segments</h2><ul>{segments}</ul><form method='post' action='/aha/{session_id}/review'><input type='hidden' name='csrf_token' value='{{csrf}}'><fieldset><legend>Graphs</legend><label>Nodes: source ID | node ID | type | label | segment reference<textarea required name='nodes' placeholder='target-01|n1|state|Input|target-01:seg-0001'></textarea></label><label>Relations: source ID | relation ID | type | source node | target node | orientation | segment reference<textarea required name='relations' placeholder='target-01|r1|causes|n1|n2|forward|target-01:seg-0001'></textarea></label></fieldset><fieldset><legend>Mappings</legend><label>Node maps: donor source ID | donor node ID | target node ID<textarea required name='node_maps'></textarea></label><label>Relation maps: donor source ID | donor relation ID | target relation ID<textarea required name='relation_maps'></textarea></label><label>Invariants: donor source ID | name | statement<textarea required name='invariants'></textarea></label><label>Disanalogies: donor source ID | explicit difference<textarea required name='disanalogies'></textarea></label><label>Scale transformations: donor source ID | transformation or none<textarea required name='scale_transforms'></textarea></label></fieldset><fieldset><legend>Hypothesis and smallest falsification test</legend>{fields}</fieldset><button type='submit'>Evaluate proposed bridge</button></form>")


def _review(root: Path, session_id: str) -> HTMLResponse:
    import json
    case = json.loads((root / "aha_case.json").read_text(encoding="utf-8"))
    score_report = json.loads((root / "review" / "score_report.json").read_text(encoding="utf-8"))
    bridge = json.loads((root / "review" / "bridge_evidence_map.json").read_text(encoding="utf-8"))
    inventory = read_inventory(root)
    sources = "".join(f"<li>{escape(s['role'])}: {escape(s['label'])}; domain {escape(s['domain'])}; family {escape(s['source_family_id'])}</li>" for s in inventory)
    maps = "".join(f"<li>{escape(item['mapping_id'])}: " + ", ".join(f"{escape(pair['donor_relation_id'])} → {escape(pair['target_relation_id'])}" for pair in item["mapped_relations"]) + "</li>" for item in bridge["mappings"])
    artifacts = "".join(f"<li><a href='/aha/{session_id}/artifact/review/{name}'>{escape(name)}</a></li>" for name in ("aha_case_normalized.json", "bridge_evidence_map.json", "falsification_suite.json", "score_report.json", "human_review_summary.md", "artifact_manifest.json", "SHA256SUMS.txt"))
    def section(title: str, content: str) -> str: return f"<h2>{title}</h2><p>{content}</p>"
    def graph(graph: dict) -> str:
        nodes = ", ".join(f"{escape(node['node_id'])} ({escape(node['label'])})" for node in graph["nodes"])
        relations = ", ".join(f"{escape(relation['relation_id'])}: {escape(relation['source_node_id'])} → {escape(relation['target_node_id'])} ({escape(relation['relation_type'])}, {escape(relation['orientation'])})" for relation in graph["relations"])
        return f"Nodes: {nodes}. Relations: {relations}."
    unmapped = "; ".join(f"{item['mapping_id']}: " + ", ".join(item["unmapped_donor_relations"]) for item in bridge["mappings"])
    invariants = "; ".join(f"{item['mapping_id']}: " + ", ".join(f"{key} — {value}" for key, value in item["invariants"].items()) for item in bridge["mappings"])
    disanalogies = "; ".join(f"{item['mapping_id']}: " + ", ".join(item["disanalogies"]) for item in bridge["mappings"])
    def score(name: str) -> str:
        value = score_report["scores"][name]
        if name == "P_epi": return f"{value['posture']} ({value['kind']})"
        if name == "Q_AHA": return f"Nonprobabilistic attention rank {value['rank']}; authority effect {value['authority_effect']}."
        if name == "V_test": return f"Information value: {value['information_value']}; feasibility: {value['feasibility']}; cost: {value['cost']}; risk: {value['risk']}."
        return f"Scorable: {value['scorable']}; " + "; ".join(f"{key.replace('_', ' ')}: {posture}" for key, posture in value['components'].items())
    sections = [
        section("Review status and disposition", escape(score_report["disposition"])), section("Target question", escape(case["question"])),
        f"<h2>Source inventory</h2><ul>{sources}</ul>", section("Evidence segments selected for nodes and relations", "See source inventory and emitted case artifact."),
        section("Target graph", graph(case["target"])), section("Donor graphs", " ".join(graph(item) for item in case["donors"])), f"<h2>Mapped relations</h2><ul>{maps}</ul>",
        section("Unmapped donor relations", unmapped), section("Invariants", invariants), section("Disanalogies", disanalogies),
        section("Target prediction", escape(case["candidate_hypothesis"]["statement"])), section("Smallest falsification test", escape(case["falsification_test"]["test_statement"])),
        section("P_epi", score("P_epi")), section("C_bridge", score("C_bridge")), section("V_test", score("V_test")),
        section("Q_AHA", score("Q_AHA")), section("Warnings and fail reasons", escape(", ".join(score_report["fail_reasons"]) or "None")),
        f"<h2>Artifact links</h2><ul>{artifacts}</ul>", section("Nonclaims", "This package is not truth, approval, memory, publication, deployment, or release authority."),
    ]
    return _page("AHA human review", "<h1>AHA Pattern Donation review</h1><p>This review evaluates a proposed structural bridge. It does not establish that the hypothesis is true. It does not perform Sophia or Atlas review. It does not write memory, publish, deploy, or release anything. Human judgment remains required.</p>" + "".join(sections) + "<p><a href='/aha'>Start another AHA review</a></p>")


def create_aha_router(state_root: Path, csrf_check) -> APIRouter:
    router = APIRouter(prefix="/aha")
    def guarded(request: Request, form: dict) -> HTMLResponse | None:
        reason = csrf_check(request, form)
        return _error(reason, 403) if reason else None
    @router.get("")
    async def home(request: Request): return HTMLResponse(_source_form().body.replace(b"{csrf}", request.app.state.aha_csrf.encode()))
    @router.post("/intake")
    async def post_intake(request: Request, csrf_token: str = Form(""), target_file: UploadFile = File(...), target_label: str = Form(...), target_domain: str = Form(...), target_family: str = Form(...), donor_files: list[UploadFile] = File(...), donor_labels: str = Form(...), donor_domains: str = Form(...), donor_families: str = Form(...)):
        if failure := guarded(request, {"csrf_token": csrf_token}): return failure
        donors = list(zip([x.strip() for x in donor_labels.splitlines()], [x.strip() for x in donor_domains.splitlines()], [x.strip() for x in donor_families.splitlines()], donor_files))
        if not 2 <= len(donors) <= 5 or any(not all(row[:3]) for row in donors): return _source_form("AHA_DONOR_CARDINALITY")
        if len({row[2] for row in donors}) != len(donors): return _source_form("AHA_SOURCE_FAMILY_CLONE")
        uploads = [("target", target_label, target_domain, target_family, target_file)] + [("donor", label, domain, family, upload) for label, domain, family, upload in donors]
        sources=[]
        try:
            for role,label,domain,family,upload in uploads:
                name=upload.filename or ""
                if Path(name).name != name or Path(name).is_absolute() or Path(name).suffix.lower() not in {".txt", ".md"}: raise CaseValidationError("AHA_UPLOAD_FILENAME_OR_TYPE")
                content=await upload.read(MAX_SOURCE+1)
                if len(content)>MAX_SOURCE or b"\0" in content: raise CaseValidationError("AHA_UPLOAD_TOO_LARGE_OR_NUL")
                content.decode("utf-8-sig")
                sources.append({"role":role,"label":label,"domain":domain,"family":family,"content":content,"media_type":"text/markdown" if name.endswith('.md') else "text/plain"})
            if sum(len(x["content"]) for x in sources)>MAX_UPLOAD: raise CaseValidationError("AHA_UPLOAD_TOTAL_TOO_LARGE")
            session_id=secrets.token_hex(16); intake(state_root,session_id,sources)
        except (UnicodeDecodeError, CaseValidationError): return _source_form("AHA_SOURCE_INTAKE_REJECTED")
        return RedirectResponse(f"/aha/{session_id}/construct",303)
    @router.get("/{session_id}/construct")
    async def construct(request: Request, session_id: str):
        try: root=session_root(state_root,session_id); return HTMLResponse(_construct(read_inventory(root),session_id).body.replace(b"{csrf}", request.app.state.aha_csrf.encode()))
        except (OSError, CaseValidationError): return _error("AHA_SESSION_NOT_FOUND",404)
    @router.post("/{session_id}/review")
    async def post_review(request: Request, session_id: str):
        form=await request.form()
        if failure:=guarded(request,dict(form)): return failure
        try:
            root=session_root(state_root,session_id); case=build_case(read_inventory(root),{str(k):str(v) for k,v in form.items()}); run_review(root,case)
        except (OSError, CaseValidationError) as exc: return _construct(read_inventory(root),session_id,str(exc))
        return RedirectResponse(f"/aha/{session_id}/review",303)
    @router.get("/{session_id}/review")
    async def review(session_id: str):
        try:return _review(session_root(state_root,session_id),session_id)
        except (OSError, CaseValidationError):return _error("AHA_REVIEW_NOT_FOUND",404)
    @router.get("/{session_id}/artifact/{artifact_path:path}")
    async def artifact(session_id: str, artifact_path: str):
        try:
            root=session_root(state_root,session_id); candidate=(root / unquote(artifact_path)).resolve()
            if ".." in artifact_path or candidate.is_symlink() or root.resolve() not in candidate.parents or not candidate.is_file(): raise ValueError
            return FileResponse(candidate,media_type="application/octet-stream",filename=candidate.name,headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
        except (OSError, ValueError, CaseValidationError): return _error("AHA_ARTIFACT_PATH_REJECTED",404)
    return router
