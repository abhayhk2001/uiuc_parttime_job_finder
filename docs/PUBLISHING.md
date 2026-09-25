# Publishing the UIUC Part-Time Job Scanner

Step-by-step instructions for going from "code on my laptop" to "students
double-click an installer and the app launches without Gatekeeper
complaints". This covers the full pipeline for macOS, which is the only
target the project supports today.

If you only want to run the app locally, you can stop after step 4 --
the bundle runs perfectly well ad-hoc-signed.

---

## Step 1 — Apple Developer Program membership

Required for distributing to other Macs. Apple's Gatekeeper refuses
to launch an unsigned or ad-hoc-signed `.app` from outside the App
Store without a user-visible "right-click > Open" workaround.

- Enroll at https://developer.apple.com/programs/enroll/.
- Cost: $99/year (individual or organisation).
- Approval can take 24-48 hours; don't leave this to the day of
  release.

You'll receive a Team ID (10-character alphanumeric, e.g.
`ABCDE12345`). Keep this handy -- it goes into the notarization
profile and the codesign identity.

---

## Step 2 — Developer ID Application certificate

This is what lets Apple's codesign tool associate the `.app` with your
identity.

1. Open **Keychain Access** on your Mac.
2. **Keychain Access → Certificate Assistant → Request a Certificate
   From a Certificate Authority…**
3. Fill in:
   - User Email Address: your Apple ID email
   - Common Name: anything (your name is fine)
   - Request is: **Saved to disk**
4. Save the `.certSigningRequest` file.
5. Go to https://developer.apple.com/account/resources/certificates/list.
6. Click the **+** button, choose **Developer ID Application**, and
   upload the CSR.
7. Download the resulting certificate (`.cer`) and double-click it to
   add it to your login keychain.
8. Verify with `security find-identity -p codesign -v`:
   ```
   1) ABCDEF1234567890ABCDEF1234567890ABCDEF12 "Developer ID Application: Your Name (ABCDE12345)"
   ```
   The string `"Developer ID Application: Your Name (TEAMID)"` is
   what you'll set as `CODESIGN_IDENTITY`.

---

## Step 3 — App-specific password + notarytool keychain profile

The notarization step talks to Apple's notary service. It needs your
Apple ID credentials, but you shouldn't put them in scripts.

1. Go to https://appleid.apple.com/account/manage and sign in.
2. Under **App-Specific Passwords** (or **Security** → **App-Specific
   Passwords** depending on UI), generate a new password. Label it
   `notarytool-jobscanner` (or whatever). Copy the password -- you
   can't see it again.
3. Store it in the macOS keychain via `notarytool`:
   ```bash
   xcrun notarytool store-credentials jobscanner-notary \
       --apple-id you@example.com \
       --team-id  ABCDE12345 \
       --password <paste-the-app-specific-password>
   ```
   The profile name (`jobscanner-notary` here) is what you'll set as
   `NOTARY_PROFILE`. Verify with:
   ```bash
   xcrun notarytool list-credentials
   ```

---

## Step 4 — Build the `.app` bundle

The included `build-mac.sh` does everything in a fresh virtualenv so the
bundle is reproducible:

```bash
./build-mac.sh
```

This:
- Creates a throwaway venv at `.build-venv/`.
- Installs the project + `pyinstaller` into it (only declared deps --
  no stray matplotlib/numpy leaking from the dev env).
- Runs `pyinstaller pyinstaller.spec`.
- Trims five unused Qt frameworks from the bundle
  (`QtPdf`, `QtSvg`, `QtVirtualKeyboard`, `QtQmlWorkerScript`,
  `QtVirtualKeyboardQml` -- verified safe to remove; the rest are
  transitively required by `QtCore` on macOS).
- Output: `dist/UIUC Part-Time Job Scanner.app` (~95 MB).

Ad-hoc signing is the default -- sufficient for local use, **not** for
distribution.

---

## Step 5 — Sign + notarize

For distribution, set the env vars and re-run:

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (ABCDE12345)" \
NOTARY_PROFILE="jobscanner-notary" \
  ./build-mac.sh
```

This rebuilds the bundle, then `scripts/sign-and-notarize.sh` runs:

1. **Deep codesign** with `--options runtime` + `entitlements.plist`
   (hardened runtime + JIT + library-validation off -- PyInstaller
   bundles Qt's frameworks without re-signing each one, so library
   validation has to be disabled for the bundle to launch).
2. **Notarize** via `xcrun notarytool submit --wait` -- this takes
   ~1-5 minutes depending on Apple's queue.
3. **Staple** the notarization ticket onto the bundle so recipients
   don't need an internet connection to verify.

Verify:

```bash
codesign --verify --deep --verbose=2 \
    "dist/UIUC Part-Time Job Scanner.app"
spctl --assess --type execute --verbose=2 \
    "dist/UIUC Part-Time Job Scanner.app"
xcrun stapler validate "dist/UIUC Part-Time Job Scanner.app"
```

All three should succeed silently for a properly notarized bundle.

---

## Step 6 — Package for distribution

A `.app` bundle is technically a folder, so handing it to someone
directly is awkward. Wrap it in a `.dmg` (the macOS-standard disk
image):

### Option A: Manual `.dmg`

```bash
mkdir -p dist/dmg-staging
cp -R "dist/UIUC Part-Time Job Scanner.app" dist/dmg-staging/

# Create the dmg. The -sectorsize 2048 + -fs HFS+ keep the image
# mountable on older macOS releases.
hdiutil create -volname "UIUC Part-Time Job Scanner" \
    -srcfolder dist/dmg-staging \
    -ov -format UDZO \
    "dist/UIUC Part-Time Job Scanner.dmg"

rm -rf dist/dmg-staging
```

### Option B: `create-dmg` (fancier, optional)

```bash
brew install create-dmg

create-dmg \
    --volname "UIUC Part-Time Job Scanner" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "UIUC Part-Time Job Scanner.app" 175 190 \
    --hide-extension "UIUC Part-Time Job Scanner.app" \
    --app-drop-link 425 190 \
    "dist/UIUC Part-Time Job Scanner.dmg" \
    "dist/"
```

Either way, sign the `.dmg` too (otherwise recipients see a "this
came from the internet" warning on first open):

```bash
codesign --sign "$CODESIGN_IDENTITY" --timestamp "dist/UIUC Part-Time Job Scanner.dmg"
```

---

## Step 7 — Distribute

A few options, in increasing order of polish:

### GitHub Releases (simplest)

```bash
gh release create v0.2.0 \
    "dist/UIUC Part-Time Job Scanner.dmg" \
    --title "UIUC Part-Time Job Scanner v0.2.0" \
    --notes "First public release. See the README for setup."
```

### Direct download

Upload the `.dmg` to whatever file host you have (S3 + CloudFront,
Google Drive, a personal website). Email / Slack the link to your
students.

### Mac App Store

Out of scope for this project (would require a sandboxed version, an
App Store Connect entry, etc.). The notarization step you already did
satisfies Gatekeeper; the App Store has additional review requirements.

---

## Step 8 — Recipient install + first-run data

The recipient drags the `.app` into `/Applications`, double-clicks, and
the app launches. Empty DB.

To seed them with your existing scan data, two options:

### Option A — Bundle the data into the `.app`

Add a `data/jobs.db` (and `keywords.json`) under `<repo>/data/` *before*
running `./build-mac.sh`. PyInstaller's spec picks them up via the
`datas=[(str(REPO_ROOT / "keywords.json"), ".")]` entry; add a similar
line for `data/jobs.db` if you want to ship pre-populated. Update
`paths.py`'s `_bundled_keywords_path()` analogously to look for
`data/jobs.db` in the bundle.

This is the right answer when you want every recipient to start with
the same baseline (e.g. an instructor shipping the same DB to a whole
class).

### Option B — Let each recipient import their own

Use the migration CLI. Recipients run:

```bash
jobscanner import ~/path/to/their/jobs.db --apply
```

The CLI writes the imported DB into the AppData directory; the `.app`
picks it up on next launch. (See `scripts/migrate-to-appdata.py` for
the same logic exposed as a developer tool for moving your source-tree
DB into AppData during local testing.)

---

## Step 9 — Verify the release

After publishing, do one more round of sanity:

1. Download the `.dmg` from wherever you published it, onto a Mac
   **that isn't yours**.
2. Drag the `.app` into `/Applications`.
3. Double-click it. First-launch Gatekeeper prompt should say
   "Developer ID Application: Your Name" and offer Open.
4. Click Open. The app should launch with no further prompts.
5. Run a scan from inside the app. Confirm the DB writes to
   `~/Library/Application Support/UIUC Part-Time Job Scanner/`.
6. Quit and relaunch. Confirm the data is still there (AppData
   persistence).

If any of these steps fails, the most common cause is incomplete
notarization (re-run `xcrun stapler staple` on the bundle). Apple's
system log (`Console.app`, search for `notarytool` or `codesign`)
will tell you what Gatekeeper is unhappy about.

---

## Quick reference

| Step | Command | Time |
| ---- | ------- | ---- |
| 1. Apple Developer Program | https://developer.apple.com/programs/enroll/ | 24-48h approval |
| 2. Developer ID cert | Keychain Access + Apple dev portal | 5 min |
| 3. App-specific password | `xcrun notarytool store-credentials ...` | 2 min |
| 4. Build (unsigned) | `./build-mac.sh` | 3-5 min |
| 5. Sign + notarize | `CODESIGN_IDENTITY=... NOTARY_PROFILE=... ./build-mac.sh` | 5-10 min (notarization queue) |
| 6. Package as .dmg | `hdiutil create ...` | 30 sec |
| 7. Distribute | `gh release create ...` | 1 min |
| 8. Verify on a clean Mac | see above | 5 min |

Total wall-clock time after Apple Developer Program approval: ~25 min.
