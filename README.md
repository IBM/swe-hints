# Hints

This repo about analyze, generate and unify hints in current repo level coding problems.

folders - purpose:
* `analyze_hint`: helper scripts of analyze hints, also a garbage collection of helper scripts
* `helper_code`: helper code on the leave one out experiments, including data prepare and analysis
* `identity_projection`: identity projection experiments given selection, currently empty, maybe merged into `src`
* `identity_selection`: identity selection experiments given projection, currently has defuse2.py, feabench, nocode, and swebenchpro.
* `leave_one_out`: leave one out experiments, contains README inside.
* `printing`: instances printing scripts, contains README
* `repos`: location to store github repos for hint generation, contains scripts.
* `src`: extract identifier hints. contains outdated README, but suffice to see the functions 
* `mini-swe-agent`: changes to run mini swe agent
* `taxonomy_graph`: the tools to draw the taxonomy graph.
`requirements.txt` is meant for everything except `mini-swe-agent` and `taxonomy_graph`. `mini-swe-agent` uses the environment from the official `mini-swe-agent` github repo. `taxonomy_graph` folder is self-contained.

## Contributing

Pull requests are very welcome! Make sure your patches are well tested.
Ideally create a topic branch for every separate change you make. For
example:

1. Fork the repo
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes (`git commit -am 'Added some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create new Pull Request

## License

All source files must include a Copyright and License header. The SPDX license header is 
preferred because it can be easily scanned.

If you would like to see the detailed LICENSE click [here](LICENSE).

```text
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
```
