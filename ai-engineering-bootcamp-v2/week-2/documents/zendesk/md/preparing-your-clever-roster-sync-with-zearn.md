---
doc_id: preparing-your-clever-roster-sync-with-zearn
source_url: https://help.zearn.org/hc/en-us/articles/38741926747671-Preparing-Your-Clever-Roster-Sync-with-Zearn
title: Preparing Your Clever Roster Sync with Zearn
source_site: help.zearn.org
source_type: zendesk
language: en
article_id: 38741926747671
section: Clever Integration
category: Get set up
updated_at: '2026-03-06T14:13:12Z'
scraped_at: '2026-07-24T19:42:05Z'
extraction_method: playwright
word_count: 485
---

# Preparing Your Clever Roster Sync with Zearn

The Zearn/Clever integration pulls information that exists within the district’s SIS directly into Zearn, and it allows for automated roster management. To ensure successful implementation, it’s important to have the SIS-to-Clever integration set up properly. Below are items that should be validated before connecting with Zearn through Clever. If you have any questions about your specific SIS-to-Clever integration, or about making changes to it, please contact Clever directly at enterprise-support@clever.com.

Clever Sections

When integrating with Zearn through Clever, Sections in Clever translate directly to Classrooms on Zearn. The sections being shared with Zearn through Clever should reflect the specific math classrooms that exist within your school. For example, if your district’s SIS is organized by homeroom and students rotate for math, the specific rosters for math class must be added as sections assigned to the proper teacher.

Administrators within Clever

There are two ways users can have administrative access in Zearn. The first method is through how user profiles are set up within Clever. A school or district administrator in Clever translates directly to a school or group administrator in Zearn. Members of your district’s Clever Team will be assigned group admin access within Zearn. The second method is through the role promotion functionality within Zearn. School or Group administrators of a Zearn Math School Account rostered can make edits to staffs' roles directly in Zearn. It’s critical to have administrators set up in a district’s Zearn Math School Account to access the associated Admin Reports.

Grade-level assignment

Prior to initially connecting with Zearn, ensure all student’s grade-level assignments are accurate within Clever. A student’s grade assignment translates to the initial Digital Lesson assignment within Zearn. This information is used only during the initial Clever-to-Zearn sync. Any edits to a student’s grade-level information in Clever after the initial sync will not update the student’s Digital Lesson assignment.

Classroom sharing

If there are coaches or aides who will need access to student information across multiple classrooms, ensure that they are set up properly within Clever as shared teachers (within Clever, shared teachers are called alternate or co-teachers). Individuals who are set up as shared teachers for a classroom will have access to that classroom’s Zearn Math Class Reports.

Sync timing

Zearn will sync roster information through Clever nightly, around 4:00 a.m. EST. In order to ensure that there isn’t any disparity during the school day, we recommend updating the SIS-to-Clever sync to this schedule. Keep in mind that even a small discrepancy between the information shared through Clever and the information that exists in Zearn may cause the instant login functionality to fail.

Requesting Out-Of-Sequence Syncs

If roster changes must be made during the school day, please contact schoolaccounts@zearn.org after syncing the updated information from the district’s SIS to Clever. Zearn will then be able to run an out-of-sequence sync to pull in the updated information from Clever.
