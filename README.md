# Real-Time Crypto Scanner - Deployment Guide

## 📦 Files for Deployment

Your repository should contain these files:
- `trade-script.py` - Main scanner script
- `requirements.txt` - Python dependencies
- `start.sh` - Startup script
- `railway.json` - Railway configuration
- `Procfile` - Alternative deployment config
- `.python-version` - Python version specification

## 🚀 Deploy to Railway

### Method 1: GitHub Integration (Recommended)

1. **Push files to GitHub:**
   ```bash
   git add .
   git commit -m "Add deployment configuration"
   git push origin main
   ```

2. **Deploy on Railway:**
   - Go to [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your `trade-screener` repository
   - Railway will automatically detect the configuration

3. **That's it!** Railway will:
   - Install dependencies from `requirements.txt`
   - Run `start.sh` to start your scanner
   - Keep it running 24/7

### Method 2: Railway CLI

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Deploy
railway up
```

## 🔧 Alternative Platforms

### Render.com
1. Create new "Background Worker"
2. Connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python trade-script.py`

### Heroku
```bash
git push heroku main
```
(Procfile is already configured)

### DigitalOcean App Platform
- Import from GitHub
- Detects Python automatically
- Uses start.sh

## ✅ Verification

After deployment, check:
1. Telegram message: "🚀 REAL-TIME Scanner Started"
2. Railway logs show: "WebSocket connected"
3. No error messages in logs

## 📝 Files Explained

- **start.sh**: Tells Railway how to start your app
- **requirements.txt**: Lists Python packages to install
- **railway.json**: Railway-specific configuration
- **Procfile**: Heroku/Railway process definition
- **.python-version**: Specifies Python 3.11

## ❌ Troubleshooting

**"Script start.sh not found"**
→ Make sure all files are committed and pushed to GitHub

**"Module not found"**
→ Check requirements.txt is present and correct

**"Permission denied"**
→ Make start.sh executable:
```bash
chmod +x start.sh
git add start.sh
git commit -m "Make start.sh executable"
git push
```

**Scanner not receiving alerts**
→ Check Telegram bot token and chat ID are correct in trade-script.py

## 🎯 Next Steps

1. Push all files to GitHub
2. Connect Railway to your repo
3. Watch it deploy automatically
4. Receive Telegram alerts!

Your scanner will run 24/7 in the cloud! 🚀
