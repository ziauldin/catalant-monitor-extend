# Railway Deployment Guide

## Quick Deploy to Railway 🚂

### Step 1: Prepare Your Repository

All necessary files are already created:
- ✅ `Procfile` - Tells Railway how to run the app
- ✅ `railway.json` - Railway configuration
- ✅ `nixpacks.toml` - System dependencies (Chrome + ChromeDriver)
- ✅ `runtime.txt` - Python version specification
- ✅ `requirements.txt` - Python dependencies
- ✅ `.env.example` - Template for environment variables

### Step 2: Push to GitHub

```bash
git add .
git commit -m "Add Railway deployment configuration"
git push origin main
```

### Step 3: Deploy on Railway

1. **Sign up for Railway**
   - Go to [railway.app](https://railway.app)
   - Sign in with GitHub

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `catalant-monitor` repository
   - Railway will automatically detect the configuration

3. **Configure Environment Variables**
   - In your Railway project, go to **Variables** tab
   - Add these variables:

   ```
   CATALANT_EMAIL=your_catalant_email@example.com
   CATALANT_PASSWORD=your_catalant_password
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SENDER_EMAIL=your_gmail@gmail.com
   SENDER_PASSWORD=your_gmail_app_password
   RECIPIENT_EMAILS=recipient1@example.com,recipient2@example.com
   HEADLESS=True
   ```

4. **Deploy**
   - Railway will automatically build and deploy
   - Check the logs to verify it's running

### Step 4: Set Up Cron Schedule (Optional)

Since this script runs once and exits, you have two options:

#### Option A: Use Railway Cron (Recommended)
Railway doesn't have built-in cron, but you can use:
- **Railway + GitHub Actions** (trigger every 30 minutes)
- **Railway + External Cron Service** (cron-job.org, EasyCron)

#### Option B: Convert to Continuous Loop
Add a loop to `script_clean_single.py` to run continuously:

```python
# At the end of main():
if __name__ == "__main__":
    while True:
        main()
        print(f"⏰ Next check in 30 minutes...")
        time.sleep(1800)  # 30 minutes
```

### Important Notes

1. **Gmail App Passwords**
   - Enable 2-Step Verification in Google Account
   - Create App Password at: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - Use the 16-character app password (not your regular password)

2. **Headless Mode**
   - MUST be set to `True` on Railway (no display available)

3. **Railway Free Tier**
   - $5/month credit (enough for this lightweight app)
   - Sleep after inactivity (won't affect scheduled runs)

4. **ChromeDriver**
   - Automatically installed via `nixpacks.toml`
   - No manual setup needed

### Troubleshooting

**If deployment fails:**
1. Check Railway logs for errors
2. Verify all environment variables are set
3. Ensure `HEADLESS=True`
4. Check that Chrome/ChromeDriver installed correctly

**If emails don't send:**
1. Verify Gmail App Password (not regular password)
2. Check SMTP settings are correct
3. Look for authentication errors in logs

**If login fails:**
1. Verify Catalant credentials
2. Check if cookies are being saved
3. May need to login manually first time

### Alternative: Use GitHub Actions Instead

If you prefer a completely free solution, use GitHub Actions with cron:

```yaml
# .github/workflows/monitor.yml
name: Monitor Catalant
on:
  schedule:
    - cron: '*/30 * * * *'  # Every 30 minutes
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: |
          pip install -r requirements.txt
          python script_clean_single.py
        env:
          CATALANT_EMAIL: ${{ secrets.CATALANT_EMAIL }}
          CATALANT_PASSWORD: ${{ secrets.CATALANT_PASSWORD }}
          SMTP_SERVER: ${{ secrets.SMTP_SERVER }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SENDER_EMAIL: ${{ secrets.SENDER_EMAIL }}
          SENDER_PASSWORD: ${{ secrets.SENDER_PASSWORD }}
          RECIPIENT_EMAILS: ${{ secrets.RECIPIENT_EMAILS }}
          HEADLESS: 'True'
```

### Cost Comparison

| Platform | Cost | Setup Difficulty | Reliability |
|----------|------|------------------|-------------|
| **GitHub Actions** | FREE | Easy | Excellent |
| **Railway** | $5/month credit | Very Easy | Excellent |

## Support

For issues, check:
- Railway logs: `railway logs`
- Script output in Railway dashboard
- Environment variables are properly set
