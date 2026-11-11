# Usage Reporting and Privacy

If you'd like to contribute to our research and help us improve FishEye, you can choose to share a short summary of each
job you run with the FishEye team. These summaries help us understand how FishEye is being used, evaluate application 
performance, identify issues, and support future research, including improvements to fish counting and model calibration.

**Sharing is completely optional and turned off by default**. The first time you open FishEye, you'll be asked whether you'd 
like to participate. Nothing is sent before you choose, and nothing is sent if you
choose **Don't send anything**.

## Your choices

| Choice | What happens |
|--------|--------------|
| **Don't send anything** | Nothing is collected or sent. |
| **Send anonymously** | Job summaries are sent without your name, institution, or email address. |
| **Send, and the team may contact me about my results** | Job summaries are sent along with the name, institution, and email you enter, so the team can follow up with you about your results. Only email is required. |

You can change your choice at any time with the **Change** link at the bottom
of the FishEye window.

## What's sent

One summary per job, containing:

**About the job**
- A random ID for the job. It's made up fresh for each job and isn't tied to
  you or your computer.
- FishEye app version and model version
- Operating system (for example, macOS or Windows)
- Whether the job ran on CPU or GPU
- Whether the job finished, failed, or was cancelled, and if it failed, the
  *type* of error (for example, "file not found"), never the error message
- When the job started and finished, and how long it took

**Settings you used**
- Number of files in the job
- Which output files you chose to export
- Upstream direction and distance offset

**Results for each file**
- Upstream, downstream, and net fish counts
- Number of fish tracked and counted
- Average, median, and spread of bounding box width in meters

Files are identified only by their position in the job (first, second,
third, …), **never by name**.

**Only if you chose to be contacted:** the name, institution, and email you
entered.

### Example

This is what one summary looks like for a job with one file, sent
anonymously:

```json
{
  "schema_version": 1,
  "job_id": "3f1c9a52-8e4b-4d7a-9c21-6b0e5f2d8a17",
  "app_version": "1.0.1",
  "detector_version": "yolov5m-v0",
  "os": "darwin",
  "device": "mps",
  "status": "completed",
  "error_type": null,
  "started_at": "2026-11-09T14:02:11",
  "finished_at": "2026-11-09T14:09:47",
  "duration_seconds": 456.0,
  "processing_seconds": 449.2,
  "file_count": 1,
  "export_options": ["summary_csv", "detailed_csv", "fc_txt"],
  "upstream_direction": "left",
  "distance_offset": 0.0,
  "counts": [
    {"file_index": 0, "absolute_up": 14, "absolute_down": 3, "net_count": 11}
  ],
  "track_stats": [
    {
      "file_index": 0,
      "num_tracks": 22,
      "num_counts": 17,
      "avg_bbox_width_meters": 0.61,
      "median_bbox_width_meters": 0.58,
      "std_bbox_width_meters": 0.12
    }
  ]
}
```

## What's never sent

- Your sonar files (ARIS or DIDSON) or any images from them
- File names or folder paths
- Full error messages, since they often contain file paths
- FishEye's logs
- Your IP address is not included in job summaries.

## When it's sent

Summaries aren't sent the moment a job finishes. FishEye saves them on your
computer and sends them together **about once a day** while the app is open.
If you're offline, they wait and go out the next time FishEye can connect.
FishEye keeps at most 500 unsent summaries, and none older than 90 days.

Your name, institution, and email are never saved alongside the waiting
summaries. They're added only at the moment of sending, and only if your
choice at that moment is to be contacted.

## Changing your mind

- **Switching to Don't send anything** deletes any summaries waiting on your
  computer, so they're never sent. Summaries already sent aren't affected. 
- **Switching from contact to anonymous** means your name, institution, and email aren't
  sent with any later summaries, including ones that were waiting to be sent.
- **Turning it on later** only sends summaries for jobs you run from then on,
  not jobs you ran before.

## Who can see it

Summaries are stored in a private storage account managed by the FishEye team. 
Access is limited to authorized FishEye team members and system administrators.

For questions or requests regarding summaries associated with your contact details, please email fisheye@caltech.edu.
