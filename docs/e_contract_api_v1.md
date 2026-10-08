# E-Contract API V1

Backend answer to `e_contract_mobile_api_v1.md`. Conventions (auth, `{"error": code}`,
UTC timestamps with offset, bare dates, 404 for other people's data) are those of
`docs/course_learning_api_contract_v1.md` §0.

The flow is the one the existing web contract page (`ai-asia-contract`,
`ai-academy.asia/contract/<id>`) already runs, moved into the app:

```text
1. Check details   GET  /me/contracts/{id}           → prefilled form + rules + money
2. Preview         POST /me/contracts/{id}/preview   → the filled PDF, unsigned, not saved
3. Agree + sign    POST /me/contracts/{id}/sign      → {agreed: true, signature: PNG}
4. Done            GET  /me/contracts/{id}/download  → short-lived link to the signed PDF
```

## Decisions (spec §4–§8)

| Question | Answer |
|---|---|
| Signing — app or web? (§4) | **In the app.** The student draws a signature; the backend fills the course's PDF template, places the signature and stores the signed PDF. No `sign_url`. Completion = the sign call's response (`status: "signed"`). |
| Owner (§6) | **Enrollment.** One contract per enrollment (`Student → Enrollment → Cohort → Course`). `course_id`/`cohort` are on every contract. |
| Created when (§8) | Automatically, for every **active enrollment in a course whose contract template is a PDF** (staff upload it on the course: `PUT /courses/{id}/templates/contract`, `course:edit`). It appears the first time contracts are listed — however the enrollment was made (web checkout, app, staff). No template → no contract. |
| Multiple (§7) | Yes — one per enrollment, so a student in two programmes has two. `/me/contracts` returns all of them, newest first, including signed and cancelled ones. `is_current` is `false` only for `cancelled`. Signed contracts stay downloadable. |
| Content format (§3) | **PDF.** Preview is `application/pdf` bytes; the signed PDF is a pre-signed S3 link (5 min). |
| Money on the contract | From the enrollment's ledger (`total_due` / `total_paid` / `balance`), never from the client. Frozen at signing. Discount % = (course list price − amount due) / list price. |

## Status (§5)

| Status | Meaning |
|---|---|
| `pending` | Exists, not signed yet |
| `signed` | Signed; the PDF is stored. Final for the student |
| `cancelled` | The enrollment was cancelled before signing |

```text
pending → signed            student signs
pending → cancelled         enrollment cancelled (back to pending if it is re-activated)
signed  → pending           staff reset (e.g. a wrong register number) — student signs again
```

There is no `expired`.

## Endpoints

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/me/contracts` | S | `{contracts: [...]}` |
| GET | `/me/contracts/{id}` | S | summary + `form`, `rules`, `finance`, `document` |
| POST | `/me/contracts/{id}/preview` | S | body `{form}` → `application/pdf` |
| POST | `/me/contracts/{id}/sign` | S | body `{form, agreed, signature}` → detail |
| GET | `/me/contracts/{id}/download` | S | `{url, expires_at}` — signed only |
| GET | `/admin/contracts` | staff:cohort:manage | `?course_id=&cohort_id=&student_id=&status=&limit=`; with a course/cohort/student filter it also creates contracts not opened yet — unfiltered lists only existing ones |
| GET | `/admin/contracts/{id}` | staff:cohort:manage | includes `form_data` and the frozen money |
| GET | `/admin/contracts/{id}/download` | staff:cohort:manage | `{url, expires_at}` |
| POST | `/admin/contracts/{id}/reset` | staff:cohort:manage | signed → pending; deletes the old PDF |

### `GET /me/contracts`

```json
{"contracts": [{
  "id": 12,
  "contract_number": "AIAA-C-2026-00012",
  "status": "pending",
  "enrollment_id": 40,
  "course_id": 9,
  "course": {"id": 9, "slug": "corporate-leaders", "title": {"mn": "...", "en": "..."}, "level": "adult"},
  "cohort": {"id": 3, "name": "Corporate Leaders 2026-08", "start_date": "2026-08-06", "end_date": "2026-10-30"},
  "created_at": "2026-10-08T07:00:00+00:00",
  "signed_at": null,
  "cancelled_at": null,
  "can_view": true,
  "can_sign": true,
  "is_current": true,
  "document_url": null
}]}
```

- `can_view` — signed with a PDF, or pending with a template to preview.
- `can_sign` — `pending`, enrollment active, template present.
- `document_url` — the API path of the download call once signed (it returns the S3 link).

The banner/profile row should show the contract with `can_sign: true` (if several, the
first — newest). With none signable, show the newest `is_current` one.

### `GET /me/contracts/{id}`

The summary above plus:

```json
{
  "form": {
    "last_name": "Дорж", "first_name": "Бат", "register": "",
    "phone": "99112233", "email": "bat@example.mn", "address": "",
    "guardian_relation": "", "guardian_last_name": "", "guardian_first_name": "",
    "guardian_register": "", "final_payment_date": ""
  },
  "rules": {
    "guardian_required": false,
    "final_payment_date_required": true,
    "final_payment_date_min": "2026-10-08",
    "final_payment_date_max": "2026-10-30"
  },
  "finance": {"total_due": 1000000.0, "total_paid": 400000.0, "balance": 600000.0,
              "discount_percent": 0, "currency": "MNT"},
  "document": {"format": "pdf", "preview": "/me/contracts/12/preview", "download": null}
}
```

`form` is prefilled from the profile (names, phone — the parent's phone for a junior
course — and the account email) while pending, and is what was signed afterwards.

### Form fields and validation

All strings. Same rules as the web contract page.

| Field | Required | Rule |
|---|---|---|
| `last_name`, `first_name` | yes | Cyrillic only (no Latin letters) |
| `register` | yes | 2 Cyrillic letters + 8 digits (`УБ12345678`; letters are upper-cased) |
| `phone` | yes | 8 digits — the guardian's for a junior course |
| `email` | no | e-mail format |
| `address` | yes | Cyrillic only |
| `guardian_relation`, `guardian_last_name`, `guardian_first_name` | when `rules.guardian_required` (junior course) | Cyrillic only |
| `guardian_register` | when `rules.guardian_required` | as `register` |
| `final_payment_date` | when `rules.final_payment_date_required` (balance > 0) | `YYYY-MM-DD`, between `final_payment_date_min` and `_max` |

Every field ≤ 300 characters. Unknown keys are ignored.

### `POST /me/contracts/{id}/preview`

Body `{"form": {...}}` (any subset; not validated). Answers the filled PDF without a
signature (`Content-Type: application/pdf`). Nothing is saved. Show it in a PDF viewer
with an "I have read and agree" checkbox before the signature pad.

### `POST /me/contracts/{id}/sign`

```json
{
  "form": {"last_name": "Дорж", "first_name": "Бат", "register": "УБ12345678", "...": "..."},
  "agreed": true,
  "signature": "data:image/png;base64,iVBORw0KGgo..."
}
```

`signature` is the signature pad's **PNG** (a data URL or bare base64), ≤ 2 MB and ≤ 8 megapixels
(above 0.6 megapixels it is scaled down); it must contain a drawn stroke. A white
background is made transparent. Answers `200` with the detail shape, now
`status: "signed"`, `signed_at` set, `document.download` set. The signed PDF is then
fetched with `/download`.

## Errors (§9)

| HTTP | `error` | When |
|---|---|---|
| 401 | `authentication_required`, `token_expired`, … | no / bad token |
| 403 | `forbidden` | not a student token (staff: missing `cohort:manage`) |
| 404 | `contract_not_found` | unknown id, or another student's contract |
| 400 | `agreement_required` | `agreed` is not `true` |
| 400 | `signature_required` / `invalid_signature` / `empty_signature` | missing / not a readable PNG / nothing drawn |
| 413 | `signature_too_large` | > 2 MB, or the PNG declares > 8 megapixels |
| 400 | `invalid_fields` | `fields: {"register": "invalid_format", ...}` — reasons `required`, `too_long`, `cyrillic_only`, `invalid_format`, `out_of_range` |
| 409 | `already_signed` | sign / preview a signed contract |
| 409 | `contract_cancelled` | sign / preview while the enrollment is cancelled |
| 409 | `not_signed` | download before signing (staff: reset a contract that is not signed) |
| 409 | `contract_template_missing` / `contract_template_invalid` | the course's template was removed / is not a readable PDF |
| 502 | `storage_error` | S3 failed — retry; a failed sign leaves the contract `pending` |
| 400 | `invalid_status`, `invalid_course_id`, … | staff list filters |

## Security (§10)

Every `/me/contracts/{id}` call is filtered by the signed-in student id — another
student's id answers `404 contract_not_found`. PDFs and signatures live in the private
S3 bucket (`contracts/<id>/...`); downloads are 5-minute pre-signed links.

## Template authoring (staff)

The course's contract template is a PDF with these literal placeholders, replaced in
bold upper case (same template format as `ai-asia-contract/public/templates/contract.pdf`):

`#contact_name` (contract number) · `#month` `#day` (signing date) · `#last_name`
`#first_name` `#register` · `#g_relation` `#g_last_name` `#g_first_name` `#g_register` ·
`#address_detail` · `<COVERAGE_PROGRAM>` (course title) · `#discount` `#advance` (paid)
`#balance` · `#final_payment_date` · `#phone` `#email` · `#signature` (signature image).
