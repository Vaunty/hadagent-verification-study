# Notice and source provenance

## No repository-wide license

This repository does not currently provide a license grant. Public visibility permits inspection and reference, but copyright law still applies. Do not assume that the code, data, figures, or documentation may be copied, modified, or redistributed merely because the repository is public.

No license is invented here for material whose source copy did not include one. If a license is added later, the rights holder must confirm its scope and the status of the third-party portions below.

## HadAgent snapshot

`hadagent/src/podl_chain/` and related tests are a copied research snapshot associated with the HadAgent paper, arXiv:2604.18614. The exact upstream repository and commit were not recorded with the copy, so this repository does not claim byte identity with a current author release.

HadAgent author Landy Xie consented to naming HadAgent and to public release of this research code and findings. That research-release consent is recorded by the project owner; it is not represented as a software license grant for the copied source. Copyright in upstream material remains with its respective authors.

The study's isolated verifier repair under `core/podl_verifier.py` is project work and is not presented as an upstream HadAgent fix.

## DebateCoach-derived judge

`core/judge.py` states that it was adapted from `judgeService.js` in the public [ponzek/DebateCoach](https://github.com/ponzek/DebateCoach) repository. The exact source revision used for the adaptation was not recorded. The source repository did not expose a license file during this release review, so no reuse permission is inferred.

## Research data and external assets

Large model weights, inference runtimes, benchmark source archives, local evaluation copies, generated run evidence, and private review archives are not distributed in this repository. Result documents identify the revisions and cryptographic hashes used where they were recorded. Their original licenses and terms govern separately.

The legacy LLM/VLM code was separated into the public [legacy-red-team-harness](https://github.com/Vaunty/legacy-red-team-harness) repository. Its history and dependencies have their own provenance and licensing review.

## Authorship and AI assistance

Matthew Ngoy selected and directed the research questions. AI agents made substantial contributions to experiment design, code, execution, reproduction, artifact review, visualizations, and documentation. Individual result records state the supported role attribution. AI review is not described as independent human validation.

Questions about permission or provenance should be resolved with the relevant rights holder before redistribution.
