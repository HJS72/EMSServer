# EMS Server Update Guide

## How Updates Work

The EMS Server includes automatic update checking and deployment. Here's the complete workflow:

### 1. **Version Checking** - Check if new version is available

**Via API Endpoint:**
```bash
curl http://localhost:8080/api/update/check
```

**Response Example:**
```json
{
  "current": "1.1.0",
  "latest": "1.1.0",
  "update_available": false
}
```

- `current`: Your installed version (from `/VERSION` file)
- `latest`: Latest version on GitHub
- `update_available`: Whether an update is needed

---

### 2. **Manual Update** - Update from Web Dashboard

**Method 1: Web UI Button** (On `/config` page)
- Click "Update Check" button → Shows available versions
- If update available → "Update Now" button appears
- Click to trigger `scripts/update.sh` via the API

**Method 2: Direct API Call**
```bash
curl -X POST http://localhost:8080/api/update/trigger
```

This endpoint:
1. Runs `scripts/update.sh` on the server
2. Pulls latest code from GitHub
3. Restarts the service
4. Returns new version

---

### 3. **Automatic Updates** - Scheduled Updates

**Systemd Timer Configuration:**

The system runs `ems-updater.timer` which automatically checks and updates:
- Schedule: Daily at 3 AM UTC (configurable via systemd)
- Service: `ems-updater.service`

**Check timer status:**
```bash
sudo systemctl status ems-updater.timer
sudo systemctl list-timers ems-updater.timer
```

**View update logs:**
```bash
sudo journalctl -u ems-updater.service -n 50
```

**Modify schedule (edit timer):**
```bash
sudo systemctl edit --full ems-updater.timer
# Change OnCalendar= line, e.g.:
# OnCalendar=*-*-* 03:00:00  (Daily at 3 AM)
# OnCalendar=Mon *-*-* 02:00:00  (Weekly Monday 2 AM)
```

---

## Update Process Workflow

```
┌─────────────────────────────────────────┐
│ User or Timer Triggers Update Check     │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ /api/update/check Compares Versions     │
│ (local /VERSION vs GitHub API)          │
└──────────────┬──────────────────────────┘
               ↓
        ┌──────┴──────┐
        ↓             ↓
   UPDATE      NO UPDATE
   AVAILABLE   (return current)
        │
        ↓
┌─────────────────────────────────────────┐
│ scripts/update.sh Executes:             │
│ • git pull origin main                  │
│ • systemctl restart ems-server          │
│ • Logs to /tmp/ems-updater.log         │
└──────────────┬──────────────────────────┘
               ↓
┌─────────────────────────────────────────┐
│ Service Restarts with New Code          │
│ VERSION file updated automatically      │
└─────────────────────────────────────────┘
```

---

## Files Involved

| File | Purpose |
|------|---------|
| `VERSION` | Current installed version (single line with semver) |
| `scripts/update.sh` | Update script (pulls from GitHub, restarts service) |
| `deploy/systemd/ems-updater.service` | Systemd service definition |
| `deploy/systemd/ems-updater.timer` | Systemd timer (runs service on schedule) |
| `app/main.py` | `/api/update/check` and `/api/update/trigger` endpoints |

---

## Testing Updates in Development

### Simulate a new version on GitHub:

1. **Locally:** Update VERSION to `1.2.0-test`
2. **Commit & Push:**
   ```bash
   git add VERSION
   git commit -m "chore: Bump to 1.2.0-test"
   git tag v1.2.0-test
   git push origin main v1.2.0-test
   ```

3. **On Server:** Check for new version
   ```bash
   curl http://localhost:8080/api/update/check
   # Should show: "update_available": true, "latest": "1.2.0-test"
   ```

4. **Trigger Update:**
   ```bash
   curl -X POST http://localhost:8080/api/update/trigger
   # Server pulls changes and restarts
   ```

---

## Troubleshooting

**Issue: Update not available despite new GitHub version**
- Check GitHub releases: `gh release list`
- Verify `/VERSION` format (should be single line, e.g., "1.1.0")
- Check update logs: `sudo journalctl -u ems-updater.service`

**Issue: Manual update fails**
- Check SSH key access to GitHub
- Verify git is installed on server
- Check network connectivity: `curl https://github.com`

**Issue: Service won't restart after update**
- Check systemd logs: `sudo systemctl status ems-server`
- View app logs: `sudo journalctl -u ems-server -n 100`
- Manual restart: `sudo systemctl restart ems-server`

---

## Release Process for New Versions

When you want to release a new version:

```bash
# 1. Update VERSION file locally
echo "1.2.0" > VERSION

# 2. Commit & create tag
git add VERSION
git commit -m "chore: Bump version to 1.2.0"
git tag v1.2.0

# 3. Push everything
git push origin main v1.2.0

# 4. Create GitHub release (optional, for changelogs)
gh release create v1.2.0 \
  --title "v1.2.0 - Feature Description" \
  --notes "Changelog here"
```

Once pushed, all servers will detect the new version and can auto-update!

---

## Version Format

Uses **Semantic Versioning** (semver):
- `MAJOR.MINOR.PATCH`
- Example: `1.1.0` means Major=1, Minor=1, Patch=0

When incrementing:
- **MAJOR**: Breaking changes (incompatible with old config)
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (no new features)
