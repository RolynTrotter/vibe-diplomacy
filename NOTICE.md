# Notices & attribution

## diplomacy engine and map (AGPL-3.0+)

This project depends on the [`diplomacy`](https://github.com/diplomacy/diplomacy)
package for rules adjudication, order validation, and the board map / SVG
rendering used by the visualizer. That package is licensed under the **GNU
Affero General Public License v3.0 or later (AGPL-3.0+)**.

The Pages visualizer distributes board SVGs produced by `diplomacy`'s renderer,
which embed its map artwork. Because of the AGPL's network-use terms, anyone who
interacts with the deployed site is entitled to the corresponding source — which
is satisfied by this repository being public. To stay compatible, this project is
intended to be distributed under AGPL-3.0+ terms as well.

If we ever want to relicense more permissively, we must first replace the
`diplomacy`-derived map (see the backlog ticket "Build our own
permissively-licensed map").
