# Korean UI subset

`GnuUI.woff2` derives from Pretendard Variable 1.3.9 (SIL OFL 1.1).
It preserves the original outlines and variable weight axis while merging the twelve
most frequent upstream dynamic subsets (80–91) into one shared font request.
The modified font has a separate family name. See `OFL.txt` for the original license;
`public/assets/fonts/GnuUI-OFL.txt` also includes the license in exported deployments.
Other characters use the existing Pretendard dynamic subsets.

To regenerate after `npm ci`, install `fonttools==4.66.1` and `brotli==1.2.0` in a separate
Python environment and run `python scripts/build-ui-font.py` from `nextjs/`.
No font tooling is required for a normal Next.js/Vercel build.
