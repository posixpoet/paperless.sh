# -*- coding: utf-8 -*-
"""
Author: posix.poet@gmail.com
Date: 2025-01-23
Synopsis: This script retrieves documents, correspondents, and tags from a Paperless instance, 
          handles UTF-8 data, builds an HTML email body, and sends it via the local `mail` command.

License (MIT):
Permission is hereby granted, free of charge, to any person obtaining a copy of this software 
and associated documentation files (the "Software"), to deal in the Software without restriction, 
including without limitation the rights to use, copy, modify, merge, publish, distribute, 
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is 
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies 
or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING 
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND 
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, 
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import requests
import subprocess
from paperlessconfig import settings
from datetime import datetime, date

# Configurable settings
TOKEN = settings["MYTOKEN"]
MYURL = settings["MYURL"]  # e.g., "http://paperless:8000" (no /api here)
SEARCHPATH = settings["SEARCHPATH"]
TO = settings["TO"]        # Can be a single email or a list
FROM = settings["FROM"]
SUBJECT_BASE = settings["SUBJECT"]  # Base subject, e.g. "files in need of attendance"
TIMEOUT = 7  # Request timeout in seconds
DEBUG = True  # Debug flag

# Common headers for API requests
headers = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json"
}

def debug_print(message):
    """Print debug messages if DEBUG is enabled."""
    if DEBUG:
        print(message)

def safe_request(url):
    """Make a safe HTTP GET request with a timeout and error handling."""
    try:
        debug_print(f"Requesting URL: {url}")
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {url}: {e}")
        return None

def get_correspondents():
    """Retrieve the list of correspondents."""
    url = f"{MYURL}/api/correspondents/?page_size=9999"
    data = safe_request(url)
    if not data:
        return []
    correspondents = [
        {"id": c["id"], "correspondent": c["name"]}
        for c in data.get("results", [])
        if "id" in c and "name" in c
    ]
    debug_print(f"Found {len(correspondents)} correspondents.")
    return correspondents

def get_tags_map():
    """
    Retrieve all tags across all pages and return a dictionary mapping tag_id -> tag_name.
    This prevents missing tags if they appear on pages other than page 1.
    """
    url = f"{MYURL}/api/tags/"
    all_tags = {}

    while url:
        data = safe_request(url)
        if not data:
            break  # If there's a request error or no data, stop.

        # Collect tag data from this page
        for t in data.get("results", []):
            if "id" in t and "name" in t:
                all_tags[t["id"]] = t["name"]

        # Move to the next page, if any
        url = data.get("next")

    debug_print(f"Found {len(all_tags)} tags across all pages.")
    return all_tags

def get_documents():
    """Fetch documents using the configurable SEARCHPATH."""
    url = f"{MYURL}/api/documents/{SEARCHPATH}"
    data = safe_request(url)
    if not data:
        return []
    documents = data.get("results", [])
    debug_print(f"Found {len(documents)} documents.")
    return documents

def calculate_age(created_date_str):
    """Calculate the age of a document in days."""
    if not created_date_str:
        return "N/A"
    try:
        created_date = datetime.strptime(created_date_str, "%Y-%m-%d").date()
        today = date.today()
        return (today - created_date).days
    except ValueError:
        return "N/A"

def get_document_details(doc_id):
    """Retrieve details for a specific document."""
    url = f"{MYURL}/api/documents/{doc_id}/"
    data = safe_request(url)
    if not data:
        return "N/A", "N/A", None
    return (
        data.get("original_file_name", "N/A"),
        data.get("archived_file_name", "N/A"),
        data.get("created_date", None),
    )

def build_subject_line(docs):
    """
    Build the email subject line as:
    # - files in need of attendance (# over 30days)

    Where:
        # is the total doc count.
        (# over 30days) is the count of docs older than 30 days.
    """
    total_docs = len(docs)
    over_30_count = sum(
        1 for doc in docs 
        if isinstance(calculate_age(doc.get("created_date")), int) 
        and calculate_age(doc.get("created_date")) > 30
    )
    return f"{total_docs} - files in need of attendance ({over_30_count} over 30days)"

def build_html_body(docs, correspondents, tag_map):
    """Build the HTML email body content with UTF-8 support."""
    corr_map = {c["id"]: c["correspondent"] for c in correspondents}
    # Sort documents by Age (descending)
    sorted_docs = sorted(docs, key=lambda d: calculate_age(d.get("created_date")), reverse=True)

    lines = []
    for doc in sorted_docs:
        try:
            doc_id = doc.get("id")
            corr_id = doc.get("correspondent")
            doc_tags = doc.get("tags", [])

            if not doc_id:
                continue

            corr_name = corr_map.get(corr_id, "No Correspondent")
            original_file_name, archived_file_name, created_date_str = get_document_details(doc_id)
            age = calculate_age(created_date_str)

            # Format age
            if isinstance(age, int) and age > 31:
                age_str = f"<span style='color:red;'>{age}</span>"
            else:
                age_str = str(age)

            # Map tag IDs to names
            tag_names = [tag_map.get(tid, f"Tag-{tid}") for tid in doc_tags]
            tags_str = ", ".join(tag_names) if tag_names else "None"

            # Make the correspondent's name a UTF-8 link to the file
            detail_url = f"{MYURL}/documents/{doc_id}/"
            corr_link = f"<a href='{detail_url}'><b>{corr_name}</b></a>"

            # Add blank line before each bullet
            lines.append(
                f"<br><li>"
                f"{corr_link}<br>"
                f"<b>Age (days)</b>: {age_str}<br>"
                f"<b>Tags</b>: {tags_str}<br>"
                f"<b>Original File</b>: {original_file_name}<br>"
                f"<b>Archived File</b>: {archived_file_name}<br>"
                f"</li>"
            )
        except Exception as e:
            print(f"Error processing document ID {doc.get('id', 'unknown')}: {e}")
            continue

    if not lines:
        lines.append("<li>No documents found.</li>")

    html_body = f"""
<html>
  <head>
    <meta charset="utf-8"/>
  </head>
  <body>
    <p>Here are your documents:</p>
    <ul>
      {''.join(lines)}
    </ul>
    <p>Your trusted PaperlessNGX Runner</p>
  </body>
</html>
"""
    return html_body

def send_email_with_mail_command(subject_line, body):
    """
    Send the generated email via the `mail` command in UTF-8.
    We append "; charset=UTF-8" to ensure the message is labeled correctly.
    """
    debug_print("Sending email via `mail` command...")
    try:
        # If TO is a list, pick the first recipient for demonstration
        recipient = TO[0] if isinstance(TO, list) else TO

        process = subprocess.Popen(
            [
                "mail",
                "-a", "Content-Type: text/html; charset=UTF-8",
                "-s", subject_line,
                recipient
            ],
            stdin=subprocess.PIPE,
            text=True,         # Use text mode to write strings
            encoding="utf-8"   # Ensure we're sending data in UTF-8 encoding
        )
        process.communicate(input=body)
        if process.returncode == 0:
            debug_print("Email sent successfully.")
        else:
            print("Failed to send email with the `mail` command.")
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    try:
        debug_print("Starting script...")

        # 1. Gather data
        correspondents = get_correspondents()
        tag_map = get_tags_map()
        docs = get_documents()

        # 2. Build the subject line
        subject_line = build_subject_line(docs)
        debug_print(f"Using subject: {subject_line}")

        # 3. Build the HTML body (UTF-8)
        email_body = build_html_body(docs, correspondents, tag_map)

        # 4. Send the email with UTF-8 content
        send_email_with_mail_command(subject_line, email_body)

        debug_print("Script completed successfully.")

    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == "__main__":
    main()
