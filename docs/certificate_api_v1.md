# Certificate API V1

Backend answer to `certificate_backend_requirements_v1.md`. Conventions (auth,
`{"error": code}`, UTC timestamps with offset, 404 for other people's data) are those of
`docs/course_learning_api_contract_v1.md` §0. The JSON below is real output from the test
suite (`tests/test_certificate_*.py`), base URL shortened.

## What changed for this spec

- **PDFs are generated, not uploaded.** Each course's certificate template (a PDF
  uploaded with `PUT /courses/{id}/templates/cert`) is filled the way the
  `ai-asia-contract` service filled each class's certificates: certificate number, name
  in Latin letters, issue date and a verification QR. This happens on issue. If the
  certificate was issued before the course had a template, it happens on the first
  download. Without a template the PDF is still a staff upload.
- **`GET /me/certificates`**: one call for the certificate screen, with one card per course.
- **A whole class at once**: `POST /admin/cohorts/{id}/certificates`.
- **Verification needs the QR's code** before it shows a name (anti-enumeration, §4.4).
- `certificate.can_download` tells the app whether Download will work.

## Endpoints

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `/me/certificates` | S | all my course cards (new) |
| GET | `/me/courses/{slug}/certificate` | S | one course's card (unchanged shape + `can_download`) |
| GET | `/me/certificates/{cert_number}/download` | S | `{url, expires_at}` |
| GET | `/certificates/verify/{cert_number}?code=` | — | JSON, or an HTML page for a browser (the QR) |
| GET / POST | `/admin/certificates` | staff:cohort:manage | list / issue one (eligibility checked unless `force`) |
| POST | `/admin/certificates/{id}/generate` | staff:cohort:manage | (re)build the PDF from the template |
| POST | `/admin/cohorts/{id}/certificates` | staff:cohort:manage | issue a class: `{force?, student_ids?}` |
| PUT | `/admin/certificates/{id}/file` | staff:cohort:manage | manual PDF upload (courses without a template) |
| DELETE | `/admin/certificates/{id}` | staff:cohort:manage | archive |

## Answers to §4 (backend verification)

### 4.1 Real responses

`GET /me/certificates`:

```json
{"certificates": [{
  "course": {"id": 1, "slug": "course-1", "level": null, "title": {"mn": "Хөтөлбөр 1", "en": "Leaders"}},
  "cohort": {"id": 1, "name": "Cohort 1", "start_date": "2026-10-01", "end_date": "2026-12-01"},
  "status": "issued",
  "requirements": {
    "lessons_completed": {"done": true, "percent": 100},
    "quizzes_passed": {"done": true, "passed": 0, "required": 0},
    "payment_cleared": {"done": true}
  },
  "certificate": {
    "cert_number": "AIAA-2026-00001",
    "issued_at": "2026-10-09T06:05:17.839489+00:00",
    "verify_url": "https://api.ai-academy.asia/certificates/verify/AIAA-2026-00001?code=bdbe9212144d53ba",
    "has_file": true,
    "can_download": true
  }
}]}
```

`GET /me/courses/{slug}/certificate` returns the same object without `course`/`cohort`.
Before issue it looks like `{"status": "eligible", "requirements": {...}, "certificate": null}`.

`GET /me/certificates/{cert_number}/download`:

```json
{"url": "https://<bucket>.s3.amazonaws.com/certificates/AIAA-2026-00001.pdf?X-Amz-...", "expires_at": "2026-10-09T06:10:18.095537+00:00"}
```

**Status enum:** `not_eligible` · `eligible` (meets every requirement, not issued yet) ·
`issued`.

Test data: there is no separate non-production API. In production, staff can issue a
certificate to a test student with `force: true` and archive it afterwards.

### 4.2 Issued without a PDF

- `certificate.has_file`: a PDF is stored. `certificate.can_download`: Download will
  work, because the PDF is stored or will be generated on that call.
- With a template on the course, issuing creates the PDF, so the usual case is
  `has_file: true`. `can_download: false` only happens when the course has no template
  and staff have not uploaded the file.
- In that case the download returns `404 certificate_file_missing`. Use `can_download`
  to hide the button instead of showing a generic error.
- "Not issued" is `status != "issued"` with `certificate: null`. Downloading an unknown
  number returns `404 certificate_not_found`.

### 4.3 Archived

Archiving withdraws a certificate:
- It disappears from `/me/certificates` and the course card. The card shows
  `eligible`/`not_eligible` again with `certificate: null`.
- Download and public verification both return `404 certificate_not_found`.
- It cannot be re-issued: staff get `409 already_issued` with `"archived": true`.

### 4.4 Errors and ownership

| HTTP | `error` | When |
|---|---|---|
| 401 | `authentication_required`, `token_expired`, `invalid_token` | no / bad token |
| 403 | `forbidden` | not a student token |
| 403 | `not_enrolled` | `/me/courses/{slug}/certificate` without an active enrollment |
| 404 | `course_not_found` | unknown / draft course slug |
| 404 | `certificate_not_found` | unknown number, **another student's**, or archived |
| 404 | `certificate_file_missing` | issued, no template, no upload (`can_download: false`) |
| 409 | `certificate_template_invalid` | the course template is not a readable PDF (generation on download) |
| 502 | `storage_error` | S3 failed. Retry |

Ownership is enforced server-side: the download looks a number up **together with the
signed-in student id**, so another student's number is a 404, the same as a number that
does not exist.

**Public verification.** Numbers are sequential, so they can be guessed. The QR
link carries `?code=` (a 16-character HMAC of the number, keyed with
`CERT_SIGNING_SECRET`):
- with the right code: `{"valid": true, "cert_number", "student_name", "course_title", "issued_at"}`;
- without or with a wrong code: `{"valid": true, "cert_number", "issued_at", "details_hidden": true}`.

So a guessed number reveals no name. A browser (scanning the QR) gets an HTML page
instead of JSON. `certificate.verify_url` in every response is built on the fly and always
includes the code, including for certificates issued before this change.

### 4.5 Download file

- **Format:** PDF.
- **Delivery:** a URL, not a stream. It is a pre-signed S3 link valid for **5 minutes**
  (`expires_at`).
- **File name:** `{cert_number}.pdf`.
- **Refreshing:** call the download endpoint again for a fresh link. Each call signs a
  new one; nothing is cached.
- **Preview:** open the same URL in the in-app PDF viewer. There is no separate preview
  image.

### 4.6 Requirements

They are already in every status body (`requirements`). The keys are stable; the app
supplies the labels:

| Key | Fields | Meaning |
|---|---|---|
| `lessons_completed` | `done`, `percent` | every lesson of the course completed (a course with no lessons never qualifies) |
| `quizzes_passed` | `done`, `passed`, `required` | every required, active quiz passed once |
| `payment_cleared` | `done` | the enrollment's ledger balance is ≤ 0 |

### 4.7 List

The list is `GET /me/certificates` (above):
- It includes every course with an **active** enrollment, plus any course the student
  holds a non-archived certificate for (e.g. after the enrollment ended). In the second
  case `cohort` is `null`.
- A course that is no longer public still shows when the student holds its
  certificate.
- One card per **course**. The `cohort` is the newest active one. There is no pagination,
  since a student has a handful of courses.

### 4.8 Consistency

There is one source of truth. `lessons_completed.percent` comes from the same function
as the course progress on the learning screens, so the two cannot disagree. The
certificate `status` is authoritative for eligibility, issue and download. The issue
date is `certificate.issued_at`.

### 4.9 Preview

Use the PDF URL (4.5).

## Answers to §5 / §9 (product)

1. **Eligibility.** The three requirements above, decided by the backend. "Eligible"
   does not issue anything by itself. Staff issue a certificate one at a time or for a
   whole class (`POST /admin/cohorts/{id}/certificates`). Both check eligibility unless
   `force` is set.
2. **Ownership.** Per **course** (one per student per course). The app should show one
   card per course. `/me/certificates` already does.
3. **Requirements UI.** Available now from `requirements`.
4. **Preview.** The PDF itself.
5. **Archived.** Hidden from the student.
6. **Aggregate endpoint.** Done: `/me/certificates`.

## Staff: issuing a class

`POST /admin/cohorts/{id}/certificates` with `{"force": false, "student_ids": [1, 2]}`.
Both fields are optional; without `student_ids` it covers every active student in the
cohort.

```json
{"cohort_id": 3, "course_id": 1,
 "issued":   [{"id": 7, "cert_number": "AIAA-2026-00007", "student_id": 11, "has_file": true, "...": "..."}],
 "existing": [{"id": 5, "cert_number": "AIAA-2026-00005", "student_id": 12, "...": "..."}],
 "skipped":  [{"student_id": 13, "error": "not_eligible", "requirements": {"...": "..."}, "enrolled": true}]}
```

Running it again is safe. Already-certified students are listed under `existing`, and a
missing PDF is generated for them.

## Template authoring

The template is one page, exported from Canva like the existing ones, with these literal
placeholders:

| Placeholder | Replaced with |
|---|---|
| `#certificate_no` | the certificate number |
| `#firstname #lastname` | the student's name in Latin letters (Cyrillic is transliterated) |
| `#date` | the issue date, e.g. `October 9, 2026` |
| `#capstone_topic` | left empty for now; there is no capstone title in the data yet |
| `#qr` or the sample QR | the verification QR (sample QR found in the bottom-left badge, vector or image) |

Each value takes the placeholder's own size, colour and baseline. The existing AI
Engineer, AI for Leaders, Corporate Leaders and Junior AI 10-13 / 14-18 templates work
unchanged. Fonts are bundled under the SIL Open Font License: Cormorant Garamond for
names, Open Sans for the number and date. The script font the earlier AI Engineer
certificates used (Liana) has no licence on record. Set `CERT_NAME_FONT` to a licensed
copy to use it.
