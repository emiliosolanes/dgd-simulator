"""Validate every payload the simulation can show against the DGD OpenAPI and the DGD 1.0 conformance content checks.

Usage: python tools/validate.py <path to dcsa-dgd-...-openapi-specification.yaml>

The OpenAPI comes from the DCSA DGD 1.0 package; it is not part of this repository.
Schema validation is strict: every object rejects properties the model does not define.
"""
import asyncio, copy, json, pathlib, re, sys
import yaml
from jsonschema import Draft7Validator
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRAPPER = {
    'POST /dgds': 'PostDGDeclarationsRequest', 'GET /dgds': 'GetDGDeclarationsResponse',
    'POST /dgd-feedbacks': 'PostDGDFeedbacksRequest', 'GET /dgd-feedbacks': 'GetDGDFeedbacksResponse',
    'POST /dgd-requests': 'PostDGDRequestsRequest', 'GET /dgd-requests': 'GetDGDRequestsResponse',
}

def strict(node):
    if isinstance(node, dict):
        if 'properties' in node and 'additionalProperties' not in node:
            node['additionalProperties'] = False
        for v in node.values(): strict(v)
    elif isinstance(node, list):
        for v in node: strict(v)
    return node

def blank(v): return v is None or (isinstance(v, str) and not v.strip())
LOC = lambda l: isinstance(l, dict) and (not blank(l.get('locationName')) or not blank(l.get('UNLocationCode')) or l.get('facility') or l.get('address') or l.get('geoCoordinate'))

def check_decl(d):
    e = []
    if blank(d.get('declarationReference')): e.append('declarationReference')
    if blank(d.get('issueDate')): e.append('issueDate')
    rm = d.get('resourceMetadata') or {}
    if not (isinstance(rm.get('revisionNumber'), int) and rm['revisionNumber'] > 0): e.append('revisionNumber')
    if blank(rm.get('issuedDateTime')): e.append('issuedDateTime')
    if not all(not blank(r.get('code')) for r in d.get('regulations') or [{}]): e.append('regulations.code')
    ps = d.get('parties') or []
    fn = [((p.get('party') or {}).get('partyFunction')) for p in ps]
    if not ({'CZ', 'OS'} & set(fn)) or not ({'CN', 'UC'} & set(fn)): e.append('parties CZ/OS and CN/UC')
    for p in ps:
        f = (p.get('party') or {}).get('partyFunction')
        if blank(f): e.append('partyFunction')
        if blank(p.get('partyName')) and blank((p.get('party') or {}).get('partyCode')): e.append('partyName')
        if f in ('CZ', 'OS', 'CN', 'UC') and not p.get('address'): e.append('party address')
        cc = (p.get('address') or {}).get('countryCode')
        if cc is not None and len(cc) != 2: e.append('countryCode')
    sb = d.get('shipmentBinding') or {}
    if all(blank(sb.get(k)) for k in ('carrierBookingReference', 'carrierBookingRequestReference', 'transportDocumentReference', 'shippingInstructionsReference', 'shipperReference', 'freightForwarderReference')): e.append('shipmentBinding')
    tr = d.get('transport') or {}
    if blank(tr.get('vesselName')): e.append('vesselName')
    if blank(tr.get('voyageNumber')): e.append('voyageNumber')
    if not (LOC(tr.get('placeOfReceipt')) or LOC(tr.get('portOfLoading'))): e.append('POL')
    if not LOC(tr.get('portOfDischarge')): e.append('POD')
    if not LOC(tr.get('destination')): e.append('destination')
    if tr.get('modeOfTransport') not in (None, 'VESSEL', 'RAIL', 'TRUCK', 'BARGE', 'RAIL_TRUCK', 'BARGE_TRUCK', 'BARGE_RAIL', 'MULTIMODAL'): e.append('modeOfTransport')
    utes = d.get('utilizedTransportEquipments') or []
    if not utes: e.append('utilizedTransportEquipments')
    refs = [u.get('equipmentReference') for u in utes]
    for u in utes:
        if blank(u.get('equipmentReference')): e.append('equipmentReference')
        tg = u.get('totalGrossWeight') or {}
        if blank(tg.get('unit')) or not tg.get('value'): e.append('totalGrossWeight')
        if not u.get('seals') or any(blank(s.get('number')) for s in u['seals']): e.append('seals.number')
        if blank(u.get('ISOEquipmentCode')): e.append('ISOEquipmentCode')
    def weights(o, path=''):
        if isinstance(o, dict):
            if set(o) >= {'value', 'unit'} and o.get('unit') in ('KGM', 'LBR', 'GRM', 'ONZ', 'MTQ', 'FTQ', 'LTR'):
                if not (isinstance(o['value'], (int, float)) and o['value'] > 0): e.append('measure value ' + path)
            elif set(o) >= {'value', 'unit'}: e.append('measure unit ' + path)
            for k, v in o.items():
                if k in ('temperatureControl', 'flashPoint', 'activeReeferSettings', 'radioactive'): continue
                weights(v, path + '/' + k)
        elif isinstance(o, list):
            for i, v in enumerate(o): weights(v, f'{path}/{i}')
    weights(d)
    dgs = d.get('dangerousGoods') or []
    if not dgs: e.append('dangerousGoods')
    lines = [g.get('lineReference') for g in dgs]
    for g in dgs:
        if blank(g.get('UNNumber')) and blank(g.get('NANumber')): e.append('UNNumber')
        if blank(g.get('properShippingName')): e.append('properShippingName')
        if blank(g.get('IMOClass')): e.append('IMOClass')
        if any(blank(x) for x in g.get('subsidiaryRisks') or []): e.append('subsidiaryRisks')
        if g.get('packingGroup') not in (None, 1, 2, 3): e.append('packingGroup')
        op = g.get('outerPackagings') or []
        if not op or any(not (isinstance(x.get('quantity'), int) and x['quantity'] > 0) or blank(x.get('description')) for x in op): e.append('outerPackagings')
        w = g.get('weights') or {}
        if not any(w.get(k) for k in ('grossWeight', 'netWeight', 'netExplosiveContent', 'capacity', 'actualDangerousGoodsWeight')): e.append('weights')
        if g.get('EMSNumber') is not None and not re.fullmatch(r'F-[A-Z] S-[A-Z]', g['EMSNumber']): e.append('EMSNumber ' + g['EMSNumber'])
        ec = g.get('emergencyContactDetails')
        if not ec or (blank(ec.get('phone')) and blank(ec.get('email'))): e.append('emergencyContactDetails')
        if g.get('equipmentReference') is not None and g['equipmentReference'] not in refs: e.append('dg equipmentReference')
    ex = d.get('exchange') or {}
    if ex.get('declarationStatus') not in (None, 'DRAFT', 'FINAL', 'WITHDRAWN'): e.append('declarationStatus')
    for dr in ex.get('documentReferences') or []:
        if blank(dr.get('documentID')) and blank(dr.get('documentWebURL')): e.append('document id/url')
        if any(r not in refs for r in dr.get('equipmentReferences') or []): e.append('document equipmentReferences')
        if any(r not in lines for r in dr.get('lineReferences') or []): e.append('document lineReferences')
        if dr.get('documentStatus') not in (None, 'DRAFT', 'FINAL', 'WITHDRAWN'): e.append('documentStatus')
    c = d.get('certificates') or {}
    sd = c.get('shipperDeclaration') or {}
    if blank(sd.get('signature')) or blank(sd.get('declarationDate')): e.append('shipperDeclaration')
    cp = c.get('containerPackingCertificates') or []
    if not cp or any(blank(x.get('signature')) or blank(x.get('declarationDate')) for x in cp): e.append('containerPackingCertificates')
    return e

COMBO = {'INFORMATIONAL_MESSAGE': 'INFO', 'PROPERTY_WILL_BE_IGNORED': 'WARN', 'PROPERTY_VALUE_MUST_CHANGE': 'ERROR', 'PROPERTY_VALUE_HAS_BEEN_CHANGED': 'WARN', 'PROPERTY_VALUE_MAY_CHANGE': 'WARN', 'PROPERTY_HAS_BEEN_DELETED': 'WARN'}
def check_fb(f):
    e = []
    if blank(f.get('feedbackID')) or blank(f.get('feedbackDateTime')): e.append('feedbackID/DateTime')
    if all(blank(f.get(k)) for k in ('severity', 'code', 'message')): e.append('severity/code/message')
    if f.get('severity') not in (None, 'ERROR', 'WARN', 'INFO'): e.append('severity')
    if f.get('code') is not None and COMBO.get(f['code']) != f.get('severity'): e.append('code/severity combination')
    if blank(f.get('declarationReference')) and blank(f.get('requestID')): e.append('declarationReference or requestID')
    if f.get('revisionNumber') is not None and not (isinstance(f['revisionNumber'], int) and f['revisionNumber'] > 0): e.append('revisionNumber')
    if f.get('propertyPath') is not None and not f['propertyPath'].startswith('/'): e.append('propertyPath is not a JSON Pointer')
    return e

def check_req(r):
    e = []
    if blank(r.get('requestID')) or blank(r.get('requestDateTime')): e.append('requestID/DateTime')
    sb = r.get('shipmentBinding') or {}
    if all(blank(v) for v in sb.values()): e.append('shipmentBinding')
    return e

def pointer(doc, ptr):
    cur = doc
    for part in ptr.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(cur, list): cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return 'absent-leaf'
    return cur

async def collect(params):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=__import__('os').environ.get('CHROME') or None, args=['--no-sandbox'])
        pg = await b.new_page()
        await pg.goto((ROOT / 'index.html').as_uri() + '#explore'); await pg.wait_for_timeout(300)
        out = await pg.evaluate("""(params) => { const H = window.__dgd; H.setParams(params); const d = H.data;
          return d.MSGS.map((m) => ({ id: m.id, op: m.op, box: m.box, rev: m.rev, body: d.payload(m).body })); }""", params)
        await b.close()
        return out

def main():
    spec = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))
    comps = strict(copy.deepcopy(spec['components']))
    validators = {op: Draft7Validator({'$ref': f'#/components/schemas/{name}', 'components': comps}) for op, name in WRAPPER.items()}
    combos = [{'ectPoll': e, 'shpPoll': s, 'fix': f} for e in (5, 15, 30, 60) for s in (5, 15, 30, 60) for f in (30, 60, 120, 180)]
    problems, n = [], 0
    for prm in combos[:1] + combos[1::7]:
        for m in asyncio.run(collect(prm)):
            n += 1
            for err in validators[m['op']].iter_errors(m['body']):
                problems.append(f"{prm} {m['id']} {m['op']} schema: {'/'.join(map(str, err.absolute_path))}: {err.message[:120]}")
            body = m['body']
            for d in body.get('DGDeclarations', []):
                problems += [f"{prm} {m['id']} declaration: {x}" for x in check_decl(d)]
            for f in body.get('DGDFeedbacks', []):
                problems += [f"{prm} {m['id']} feedback: {x}" for x in check_fb(f)]
            for r in body.get('DGDRequests', []):
                problems += [f"{prm} {m['id']} request: {x}" for x in check_req(r)]
    print(f'{n} payloads checked across {len(combos[:1] + combos[1::7])} what-if settings')
    for x in sorted(set(problems))[:60]: print(' ', x)
    print('OK' if not problems else f'{len(set(problems))} problems')
    return 1 if problems else 0

if __name__ == '__main__':
    sys.exit(main())
