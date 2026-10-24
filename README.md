# InstaArchive — Automated Instagram Stories & Posts on GitHub Pages

Automatically download and archive **public Instagram 24-hour Stories, Feed Posts, Carousels, and Reels** to your GitHub repository using **Apify** and **GitHub Actions**, and display them on an interactive **GitHub Pages** site.

---

## Features

- **Never Lose a 24-Hour Story**: Scheduled GitHub Actions workflow runs every 6 hours (`0 */6 * * *`) to capture ephemeral 24-hour stories before they disappear.
- **Zero Expired CDN Links**: Downloads images and videos directly into `docs/data/media/` and rewrites `docs/data/archive.json` to reference local paths.
- **Interactive Story Player & Post Gallery (`docs/`)**:
  - **Active (24h) Story Ring** with Instagram gradient + **Daily Story Archive Rings** grouped by date.
  - Fullscreen Story Viewer with segmented progress bars, keyboard shortcuts (`←`, `→`, `Space`, `Esc`), and video audio toggle.
  - Filterable Feed Grid (**Feed Posts**, **All Stories**, **Videos & Reels**) with caption/date search and multi-slide carousel lightbox.

---

## Quick Setup (3 Steps)

### 1. Set Your Target Instagram Account
Edit [`config.json`](config.json) and set `targetUsername` to the public Instagram account handle you want to archive:

```json
{
  "targetUsername": "your_public_account",
  "postsActorId": "apify/instagram-post-scraper",
  "storiesActorId": "apify/instagram-story-scraper",
  "resultsLimit": 12,
  "fetchPosts": true,
  "fetchStories": true,
  "maxArchivedPosts": 0,
  "maxArchivedStories": 0,
  "downloadTimeoutSeconds": 60
}
```

### 2. Add Your Apify API Token to GitHub Secrets
1. Create a free account at [Apify](https://apify.com/) (includes \$5/month in free usage credits) and copy your **Personal API Token** from **Settings → Integrations**.
2. In your GitHub repository, navigate to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret**:
   - **Name**: `APIFY_API_TOKEN`
   - **Secret**: `<your-apify-api-token>`

### 3. Enable GitHub Pages
1. In your GitHub repository, navigate to **Settings → Pages**.
2. Under **Build and deployment → Source**, select **GitHub Actions**.
3. Trigger your first sync manually from **Actions → Sync Instagram Archive & Deploy GitHub Pages → Run workflow**.

---

## Running Locally

```bash
pip install -r scripts/requirements.txt pytest

# Run unit tests
pytest

# Run a live sync locally
export APIFY_API_TOKEN="apify_api_..."
python scripts/sync_instagram.py --username yukipanvel
```
