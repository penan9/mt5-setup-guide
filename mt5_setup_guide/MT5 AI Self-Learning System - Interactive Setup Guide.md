# MT5 AI Self-Learning System - Interactive Setup Guide

An interactive step-by-step website guide for traders to configure and deploy the MT5 AI Self-Learning System.

## Features

- 📱 **Fully Responsive Design** - Works on desktop, tablet, and mobile devices
- 🎯 **Step-by-Step Guide** - 5 comprehensive steps from setup to maintenance
- 💻 **Code Copy Feature** - One-click copy for all code snippets
- ✅ **Progress Tracking** - Visual progress bar and completion checklist
- 🎨 **Professional UI** - Modern, clean design with trading theme
- ⌨️ **Keyboard Navigation** - Use arrow keys to navigate between steps
- 📊 **Interactive Components** - Checklists, alerts, and visual guides

## Files Included

- `index.html` - Main HTML structure
- `styles.css` - Complete styling and responsive design
- `script.js` - Interactive functionality and navigation
- `README.md` - This file with deployment instructions

## Quick Start (Local Testing)

1. Open `index.html` in your web browser
2. Navigate through the 5 steps using the "Next" button
3. Use keyboard arrows (← →) for quick navigation

## Deploy to GitHub Pages (Free Hosting)

### Step 1: Create a GitHub Account
If you don't have one, sign up at [github.com](https://github.com)

### Step 2: Create a New Repository
1. Go to [github.com/new](https://github.com/new)
2. Repository name: `mt5-setup-guide` (or any name you prefer)
3. Description: "Interactive setup guide for MT5 AI Self-Learning System"
4. Choose "Public" (required for free GitHub Pages)
5. Click "Create repository"

### Step 3: Upload Files to GitHub
Option A: Using Git (Recommended)
```bash
# Navigate to your project directory
cd mt5_setup_guide

# Initialize git repository
git init

# Add all files
git add .

# Commit changes
git commit -m "Initial commit: MT5 setup guide website"

# Add remote repository
git remote add origin https://github.com/YOUR_USERNAME/mt5-setup-guide.git

# Push to GitHub
git branch -M main
git push -u origin main
```

Option B: Using GitHub Web Interface
1. Go to your repository on GitHub
2. Click "Add file" → "Upload files"
3. Drag and drop all files (index.html, styles.css, script.js)
4. Click "Commit changes"

### Step 4: Enable GitHub Pages
1. Go to your repository on GitHub
2. Click "Settings" (top right)
3. Scroll to "GitHub Pages" section
4. Under "Source", select "main" branch
5. Click "Save"
6. Your site will be available at: `https://YOUR_USERNAME.github.io/mt5-setup-guide`

### Step 5: Share Your Website
Your interactive setup guide is now live! Share the link with traders who need to set up the MT5 AI system.

## Alternative Free Hosting Options

### Netlify
1. Go to [netlify.com](https://netlify.com)
2. Sign up with GitHub
3. Click "New site from Git"
4. Select your repository
5. Deploy automatically

### Vercel
1. Go to [vercel.com](https://vercel.com)
2. Sign up with GitHub
3. Click "New Project"
4. Import your repository
5. Deploy in seconds

### Firebase Hosting
1. Go to [firebase.google.com](https://firebase.google.com)
2. Create a new project
3. Install Firebase CLI: `npm install -g firebase-tools`
4. Run: `firebase init hosting`
5. Deploy: `firebase deploy`

## Customization

### Change Colors
Edit the CSS variables in `styles.css`:
```css
:root {
    --primary-color: #1e3c72;
    --secondary-color: #2a5298;
    --accent-color: #00d4ff;
    /* ... more colors ... */
}
```

### Add More Steps
1. Add new section in `index.html`:
```html
<section class="step" id="step6">
    <!-- Your content here -->
</section>
```
2. Update `totalSteps` in `script.js`:
```javascript
const totalSteps = 6;
```

### Modify Content
Simply edit the text, links, and code examples in `index.html` to match your needs.

## Browser Support

- Chrome/Edge: ✅ Full support
- Firefox: ✅ Full support
- Safari: ✅ Full support
- Mobile browsers: ✅ Fully responsive

## Performance

- **Page Size**: ~50KB (very lightweight)
- **Load Time**: < 1 second on most connections
- **No External Dependencies**: Pure HTML/CSS/JavaScript
- **SEO Friendly**: Proper semantic HTML structure

## Support

For issues or questions about the setup guide, please refer to the main MT5 AI Self-Learning System documentation.

## License

This interactive setup guide is part of the MT5 AI Self-Learning System project.

---

**Created with ❤️ by Manus AI**
