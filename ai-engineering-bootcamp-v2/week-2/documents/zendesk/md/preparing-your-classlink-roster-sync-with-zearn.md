---
doc_id: preparing-your-classlink-roster-sync-with-zearn
source_url: https://help.zearn.org/hc/en-us/articles/38753783704215-Preparing-Your-ClassLink-Roster-Sync-with-Zearn
title: Preparing Your ClassLink Roster Sync with Zearn
source_site: help.zearn.org
source_type: zendesk
language: en
article_id: 38753783704215
section: ClassLink Integration
category: Get set up
updated_at: '2026-03-06T14:14:53Z'
scraped_at: '2026-07-24T19:42:04Z'
extraction_method: playwright
word_count: 509
---

# Preparing Your ClassLink Roster Sync with Zearn

Preparing your ClassLink Integration for Zearn

To ensure that all math courses with teachers and students have a Zearn profile, as well as to allow building administrators to generate school-wide reports, we recommend creating rules that share enrolled math courses and building administrators with us. This will increase the clarity of your reports. Our Deployment Team is available to help with establishing your ClassLink to Zearn Sync. Below are items that should be validated before connecting with Zearn through ClassLink. If you have questions on setting up your ClassLink Roster Server or managing your source data, we recommend reaching out to ClassLink directly at helpdesk@ClassLink.com.

ClassLink Classes

When integrating with Zearn through ClassLink, classes in ClassLink translate directly to classrooms in Zearn. The classes being shared with Zearn through ClassLink should reflect the specific math classrooms that exist in your school. For example, if your district’s SIS is organized by homeroom and students rotate for math, the specific rosters for math classes must be added as classes assigned to the proper teacher.

Grade-Level Assignment

Prior to initially connecting with Zearn, ensure all student’s grade-level assignments are accurate within ClassLink. A student’s grade assignment translates to the initial Digital Lesson assignment within Zearn. This information is used only during the initial ClassLink-to-Zearn sync. Any edits to a student’s grade-level information in ClassLink after the initial sync will not update the student’s Digital Lesson assignment.

Classroom Sharing

If there are coaches or aides who will need access to student information across multiple classrooms, ensure they are set up properly within ClassLink as a co-teacher. Individuals who are set up as co-teachers for a classroom will have access to that classroom’s Zearn Math Class Reports.

Administrators within ClassLink

There are two ways to set up users with administrative access within Zearn. The first way is through the role assignments within ClassLink. A school or district administrator in ClassLink translates directly to a school or group administrator in Zearn. A second option is available to coaches or other personnel who need access to Zearn admin reports but are assigned the teacher role in ClassLink. Users with the teacher role can have their role promoted by a School or Group Administrator within the Zearn application. It is critical to have administrators set up in a district’s Zearn Math School Account in order to access the associated Admin Reports.

Sync Timing

Zearn will sync roster information from ClassLink nightly, around 4:00 a.m. EST. In order to ensure that there isn’t any disparity during the school day, we recommend updating your SIS-to-ClassLink sync to this schedule. Keep in mind that even a small discrepancy between the information shared through ClassLink and the information that exists in Zearn may cause the instant login functionality to fail.

Requesting Out-Of-Sequence Syncs

If roster changes must be made during the school day, please contact schoolaccounts@zearn.org after syncing the updated information within your ClassLink source data. Zearn will then be able to run an out-of-sequence sync to pull in the updated information from ClassLink.
