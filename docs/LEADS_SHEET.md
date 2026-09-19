# Sending leads into a Google Sheet

Every enquiry from the public **Register your interest** form
(`/interest`) is stored in Meridian's own database and shown in the
internal console under **Leads**. That is the record. This page is about
the optional extra: mirroring each new lead into a Google Sheet as it
arrives, so the sheet can be shared, filtered and worked in by anyone.

Nothing here can lose a lead. If the sheet is misconfigured, deleted or
unreachable, the lead is still saved and still appears in the console —
it's simply marked **"not in your sheet yet"**, and delivery is retried
the next time someone opens the Leads page (five attempts, then it stops
and shows the error).

## Why a script instead of the Google Sheets API

The Sheets API needs a service-account key file to be created, downloaded,
pasted into the server and later rotated — a long-lived credential to look
after. A Google Apps Script Web App needs one URL and one shared secret,
both ordinary settings, and the script runs as you against your own sheet.
The secret is checked inside the script, so knowing the URL alone is not
enough to write rows into your sheet.

## 1. Create the sheet

1. Go to <https://sheets.google.com> and create a blank spreadsheet.
2. Name it something like **Meridian leads**.

## 2. Add the script

1. In that sheet: **Extensions → Apps Script**.
2. Delete whatever is in the editor and paste this in:

```javascript
// Must match LEADS_SHEET_SHARED_SECRET on the Meridian backend.
const SECRET = 'paste-your-own-long-random-secret-here';

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.secret !== SECRET) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: 'bad secret' }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  const lead = body.lead;
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = book.getSheetByName('Leads') || book.insertSheet('Leads');

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['Received', 'Name', 'Business', 'Phone', 'Email',
                     'Message', 'Source', 'Campaign', 'Status', 'Lead ID']);
    sheet.setFrozenRows(1);
  }

  // The apostrophe keeps the phone number as text. Without it Google
  // reads 08031112222 as a number and drops the leading zero.
  const row = [lead.received_at, lead.full_name, lead.business_name,
               "'" + lead.phone, lead.email, lead.message,
               lead.source, lead.campaign, lead.status, lead.id];

  // A repeat enquiry from the same person updates their existing row
  // rather than adding a second one.
  const lastRow = sheet.getLastRow();
  const ids = lastRow > 1
    ? sheet.getRange(2, 10, lastRow - 1, 1).getValues().map(function (r) { return r[0]; })
    : [];
  const found = ids.indexOf(lead.id);
  if (found >= 0) {
    sheet.getRange(found + 2, 1, 1, row.length).setValues([row]);
  } else {
    sheet.appendRow(row);
  }

  return ContentService
    .createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
```

3. Replace `paste-your-own-long-random-secret-here` with a long random
   string of your own. Keep a copy — you need the same one in step 4.
4. **Save** (the disk icon).

## 3. Publish it

1. **Deploy → New deployment**.
2. Click the gear beside "Select type" and choose **Web app**.
3. Set:
   - **Execute as:** Me
   - **Who has access:** Anyone
4. **Deploy**, then approve the Google permission prompt (it is your own
   script writing to your own sheet).
5. Copy the **Web app URL**. It looks like
   `https://script.google.com/macros/s/AKfy..../exec`.

"Anyone" sounds alarming but is required for a server to post to it
without a Google login. The secret in step 2 is what actually protects the
sheet, which is why it must be long and random.

## 4. Tell Meridian about it

Railway → **backend** service → **Variables**, add two:

```
LEADS_SHEET_WEBHOOK_URL=https://script.google.com/macros/s/AKfy..../exec
LEADS_SHEET_SHARED_SECRET=the-same-secret-you-put-in-the-script
```

Railway redeploys itself. The next lead lands in the sheet within seconds,
and anything that came in beforehand is delivered the next time the Leads
page is opened.

## Checking it works

Submit a test enquiry at `/interest` and watch the sheet. If the row
doesn't appear, open **Leads** in the console: a lead that hasn't reached
the sheet says **"not in your sheet yet"**, and hovering that text shows
the exact error Google returned. The usual causes are a mismatched secret
and a deployment whose access isn't set to "Anyone".
