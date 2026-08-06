# Visual Regression Policy

The required local matrix covers 360, 768, 1440 and 1920 pixel viewports with light, dark and high-contrast themes and both densities. Fixtures must be synthetic. Playwright screenshots have a maximum pixel-difference ratio of 0.001.

New screenshots are candidates, not approvals. A reviewer different from the creator checks content, privacy, theme, viewport and changed regions before approving a baseline. Missing baselines, pending differences or unreviewed accessibility evidence keep production status `NOT_CERTIFIED` and `release_allowed=false`.
