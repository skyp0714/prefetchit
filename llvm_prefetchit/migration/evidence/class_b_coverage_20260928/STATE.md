# Code-miss coverage follow-up

Started 2026-09-28 14:57:45 UTC. User requested further code-miss reduction exploration; prior commit ff14641. No new fixed time budget.

- Base: original all3 Media static binaries from class_b_dense_20260927.
- V6: 97% cumulative old baseline function profile, min caller size0, allow short IR lead, lead24,4sites/function,8hints/site, ungated static IT0.
- V6 exact NOP and weighted per-caller budget1 (same layout) built/audited. Movie old exact-IP entry target overlap18.97 ->39.18%; hints4037/4232/3922; weighted2304/2392/2244; executable growth1.10–1.42%.
- screen completed8/8 valid. Full miss reduction summed FE_L2:1.287% vs original,3.943% vs NOP; weighted0.221%/2.906%. Both blocks positive. Full E2E point CPU+0.169%,mean+0.734%; weightedCPU+0.438%,mean+0.780%. Exploratory only. Weighted1 ELF cleaned as superseded for primary miss objective; full/NOP retained as active reference. Results in screen_miss.json and screen_evaluation/evaluation.json.
- Root PTY67124 currently running capture_indirect.py, pinned84–85. No builds/disassembly until capture workload completes.
- New indirect-profile compiler mode prepared in repository, not yet compiled/tested integration. Unit selector/parser tests5pass, integration intentionally pending screen completion.
- Next: finish screen; run capture_indirect.py as root (frozen spec, train/heldout12s each all3, seed62001). Then train indirect_profile.py, compiled plugin/test fixtures, build coverage_indirect with extended callee list and --indirect-file. Profile target definitions restricted to global-name intersection of all3 originals to bind shared static libraries safely.
- Judge first screen with coverage_evaluate.py and lean_evaluate.py; retain compact data and remove rejected bulk promptly. Preserve controls only if needed for a next comparison.
- Test new policy against original and own NOP on fresh seeds, measure PMU each repeat. If repeated miss improvement, use independent confirmation; do not declare E2E success from screening.
- At end report by implementation, push authorized Git changes, retain compact evidence and clean rejected generated artifacts; stop services/restore platform/close root PTY.

Sources/benchmark directories in this root are local symlinks to prior campaign sources; NEVER delete through these symlinks. Original package/input/dependency resources remain untouched. No NAS transfers.

## 15:45 UTC update

- Captures complete: ~210k samples, no lost/throttle. Train/heldout all3 at period257,12s each. indirect_profile/aggregates.json.gz retains all main IP counts, entry IPs, unique branch edges and alias-aware pair counts plus symbol ranges. Raw/decoded/DSO copies cleaned.
- Learned107caller names85target names, restricted to global symbols common to all3 baseline images. Heldout selected edge sample share of all samples ~17.1%Movie/15.9%Compose/14.6%Rating.
- V7 coverage_indirect: static IT0 hints4161/4359/4038; target coverage of heldout main IPs57.35/52.62/46.23%; executable+1.23/1.46/1.14%. 26compiler tests passed.
- V8 coverage_indirect_lift: additionally prefetch those targets at a direct caller of each learned wrapper, one callgraph edge earlier; actual calls unchanged. hints4296/4524/4168; coverage58.63/54.60/47.54%; executable+1.27/1.52/1.17%. 27tests passed. Protocol lift_design.json frozen before V7/V8 timing.
- Code commits: bfc9da7 (coverage/dose),5361042 (LBR-trained indirect),f148b8c (one direct edge lift). Not yet pushed; final artifacts/report pending.
- Root PTY67124 now running screen_indirect_spec.json:5arms(base,indirect_nop,indirect_it0,lift_nop,lift_it0)*2blocks; seeds63001–63002,C4,60s clean ROI, all3 PMU after EACH run. NO builds/disassembly/decode while this campaign is active.
- V6full/NOP kept as fallback reference (both primary-miss blocks improved); V6weighted1 removed after compact records because weaker primary miss reduction. Current references: V6full/NOP,V7IT0/NOP,V8IT0/NOP. No policy has independently confirmed E2E gains.
- Next: finish screen (~16:20UTC), evaluate code misses and E2E separately. Select strongest minimum code-miss reduction versus original+ownNOP if both blocks positive. Retain compact evidence and immediately clean superseded bundles. Confirm selected policy on fresh seed blocks (prefer6forE2E;4miss-only is a separate explicitly labeled option), PMU each block; freeze before starting. Consider C16 only if justified by actual benefit; current scope is full Media C4, not Social or new capacity sweep.
- Pending final: test fixture artifact cleanup, readable report and compact Git evidence, push, restored-platform/service audit, root PTY exit. Do not stop at merely reporting exploratory miss reductions.

## 16:00 UTC preparation update

- Independent confirmation now frozen as6new seed blocks64001–64006,3arms, all3 primary PMU every block plus a separate frontend set (FE_L1, ICACHE_DATA_STALL, ICACHE_TAG_STALL, BACLEARS, ITLB_WALK_ACTIVE, instructions/cycles). Clean60s ROI unchanged. See confirmation_diagnostic_design.json.
- prepare_confirmation.py chooses largest minimum primary miss point improvement among qualified available V6/V7/V8 references; weighted V6 removed because weaker primary score. Then removes all superseded active ELFs after compact results. Run only after finish_indirect_screen.py.
- diagnose_selected.py is prepared: after independent confirmation completes, a separate selected candidate FE_L2+LBR capture of12s/service, analyze predecessor hint-to-miss-line associations with existing dense_cause_analysis. Retain all main-IP counts+symbols and compact aggregate, remove raw/decoded/DSO bulk. This helps distinguish static coverage from observed preceding matching hints; do not infer exact hardware fill/BTB cause.
- coverage_evaluate.py now also summarizes extra PMU sets with separate metric namespaces; not committed yet. No change to primary screen/selection metrics.
- coverage_figures.py created static coverage PNG/SVG and visually checked. docs/class_b_coverage_20260928.md is an explicit in-progress methods draft; MUST replace lead with final measured results before publishing.
- First V7 block: FE_L2sum1976.56base,2070.00NOP,1940.27IT0 (~1.8%/6.3% lower), CPU5910.23 vs5936.55base/5910.27NOP; mean3.2953 vs3.3845base/3.2785NOP. One observation only, not confirmed. Never pool with later seeds.

## Additional V9 path-coverage experiment planned16:11UTC

Code inspection found per-function global Seen target dedup can drop a hint on a disjoint branch even when retained site does not dominate it. Added explicit opt-in PREFETCHIT_DOM_PATH_DEDUP (ungated lean only), policycoverage_paths inherits V7 without lifting. New test_path_prefetch.py uses exact LLVM IR CFG: disjoint paths must retain2; dominating entry hint still allows1. NOT compiled/tested integration yet; do not build during active screen_indirect.
After current10runs finish: evaluate stage2, build_paths_plugin.py (includesnewtests), build_paths.py, audit then new3arm2block screen seeds66001–66002. Policy is frozen in path_dedup_design.json. Only after that, chooseper-service best and do6seed independent confirmation. Current prepare_confirmation.py needs extension to include this third screen and enforce its completion before selection.
Reason for iteration: static caller/target presence78–88% does not imply its hint lies on the executed branch. The new setting directly tests that source-level coverage hole. No claim yet that it explains PMU results.

## 16:19UTC stage2 complete / V9 build active

- screen_indirect10/10valid. V7 summedFE_L2 reductions2.081%vsoriginal,6.631%vsownNOP (bothblocks positive). E2E point CPU -0.303% (worse),mean -0.217%,p99 -1.240% vsoriginal; no E2E success.
- V8 lift summedFE_L2 -0.496%vsoriginal (bothblocks worse),+3.935%vsNOP. WholeCPU -0.088%,mean -1.695% vsoriginal. Global miss eligibility failed.
- Provisional service-wise ranking (bothblocks positive vsboth controls per service): MovieV7(score2.888%),ComposeV8(score2.444%),RatingV6full(score3.499%). Each preserved withits own NOP. Other V6/V7/V8 ELF components immediately cleaned; allstaticmetadata/symbols/results retained. See provisional_service_selection.json,before_paths_superseded_cleanup.json.
- RootPTY67124 currently runs build_paths_plugin.py then build_paths.py. NewpathdedupCFGtests included; inspect tests_paths.log and paths_plugin_driver.log before accepting.
- Next whenbuilddone: prepare_paths_screen.py -> screen_paths_spec.json(3arms2blocks,C4,seeds66001–66002); runlean_study.py rootpinned84–85, no concurrentbuild/decode. Then finish_paths_screen.py -> prepare_confirmation.py ->6seed confirmation. All current drivers syntaxchecked. prepare_confirmation.py already includesstage3, per-service criteria and regenerates exact-hash weightedV6 only if itwins (currentlydoesnot).
- Need independent confirmation and selected residual diagnostic, finalreport/evidence/gitpush/cleanup/restoration; do NOTfinish turnwiththese exploratorynumbers.

## 16:23UTC V9 screen active

- V9 compiler/native tests29passed; source commit4f8d8f5. Builds and IT0/exact-NOP/main-target/instruction-boundary audits complete.
- V9hints4345/4541/4203 (vsV7 4161/4359/4038), target names unchanged277/292/282. Executablegrowth1.287/1.529/1.184%. Thus adds~165–184previouslypruned path-local hints per image without broadening the target-name set.
- Test fixture trees forV7/V8/V9 cleaned after source/object/binary hashes retained; logs and29testresults preserved.
- RootPTY67124 now runs lean_study.py screen_paths_spec.json,6trials(base,paths_nop,paths_it0)*2blocks,seeds66001–66002,C4,60sROI,primary PMU bothblocks. Expected~16:43UTC finish. NO BUILD/DISASSEMBLY/TRACEDECODE during this run.
- After complete: finish_paths_screen.py then prepare_confirmation.py (service-wise selection across all3screens; preset6newseeds64001–64006, primary+separatefrontend PMU sets), then lean_study.py confirmation_spec.json. Currentreferences previouslypruned toMovieV7/ComposeV8/RatingV6full withownNOP plusall3V9. Full oldpolicybundles no longer exist, but results/metadata remain. Selector considers all measured variants regardless of file existence and can reconstruct an exact-hash weightedV6 if it wins; it doesnotcurrentlywin.
- After independent confirmation: diagnose_selected.py performs separate residualFE_L2+LBR capture and compact analysis, then cleansraw/decoded/snapshots. Need final evaluation/decision, report/effectfigure/evidence, push Git, cleanrejectedbulk, audit restoration, exitrootPTY.

## 16:43 UTC independent confirmation active

- V9 screen6/6 valid: summed FE_L2 reduction1.4494% vsoriginal,6.3969%vsownNOP. E2EpointCPU+.311%,mean-.001%,p99-1.441%vsoriginal; no confirmed E2E win.
- Final per-service selection unchanged: MovieV7 indirect,ComposeV8 lift,RatingV6 direct-full. AllV9 ELF/NOPs promptlyremoved aftercomplete outcomes/metadata/hashes retained.
- RootPTY67124 runs lean_study.py confirmation_spec.json -> confirmation.log.18fresh-stack trials(6newseeds64001–64006 xbase/selected_nop/selected_it0), separateprimary/frontend PMU aftercleanROI. NO BUILD/DISASSEMBLY/TRACEDECODE duringconfirmation. Approxfinish17:48UTC.
- Aftercompletion: diagnose_selected.py ->finish_confirmation.py -> final_retention.py. Then render_final_report.py, coverage_figures.py --effects, environmentaudit, collect_evidence.py, inspect/commit/pushGit andexitroot. Final reportlead MUSTbeactual6seedresults.
- coverage_figures.py now supports an actual-effect CI figure withseparatePMU/E2E rows. Preparedfinal_retention.py removesallunconfirmedcandidateELFs afterdiagnostics,orretainsconfirmedmisscandidate+NOPasresearchreference,E2Edecisionseparate;cleansoldpluginsandkeepslatesttestedplugin. NoNAS.
- Remoteoriginmainstillff14641 asof16:42UTC. Newlocalimplementationcommitsbfc9da7,5361042,f148b8c,4f8d8f5 areauthorizedforpush aftercomplete report/evidence.

## Confirmation wait preparation

- Added summarize_residual.py: after selecteddiagnostic, classify exact main-IP aggregates into targeted/untargeted entry/interior lines with conservative overlapping-symbol handling and alias single-counting. Preserves full function spectra and separate one-window normalization; never substitutes it for6seedPMU. Run before render_final_report.py.
- Prepared audit_finished.py: afteralltrials/profiling assert42validE2Eruns, allplatform/scheduler/module restoration, fullyscheduledprimary+extraPMU,9zero-lossPEBScaptures, no campaign containers/modules/processes. Save final_environment_audit.json beforeevidencecollection.
- Newcodecommitfde4243 addsseparatefrontendmetricnamespaces andindependent-effectCIplot (--effects). Currentreportrenderer requires residual_location_summary.json and emitsactualeffectfigurelink; italso reports3services'userCPUshareofwholeCPU andNOPmisspenalty.
- Updated final sequence: diagnose_selected.py -> summarize_residual.py -> finish_confirmation.py -> final_retention.py -> render_final_report.py -> generateeffectPNG/SVGwithcoverage_figures.py --effects -> visualinspect -> audit_finished.py -> updateSTATEcomplete -> collect_evidence.py -> verify/commit/push -> exitrootPTY.

## 17:35 UTC finalization preparation

- Independent confirmation currently13+/18 valid, no settings changed. Native compiler tests remain29; extra reporting scripts only modified.
- Added post_confirmation.py to run the frozen completion sequence safely via checked subprocesses: diagnose_selected ->summarize_residual ->finish_confirmation ->final_retention ->audit_finished, withper-step driverlogs andpost_confirmation_complete.json. Runasroot pinned84–85 ONLYafterconfirmation/complete.json. Thenrenderreport/plots/visualinspect/updateSTATE/collectevidence/verifycommitpush/exitroot.
- Fixed residualmetadata provenancepreflight: savedmetadata belongsT1source, selectedbinaryisIT0same-layout opcodepatch. NowusesauditedsourceSHA->IT0SHA chain; all3mappingchainsverified withoutnewdisassembly.
- verify_coverage_progression.py replayedall12 V5–V8 staticfigurevalues fromretainedtargetnames andsameoriginalheldoutIPcounts;allmatch. Addedsmallv5_reference_build.json snapshot+SHArecords forself-containedreplay. Thisisstaticcoverageverification,notanotherbenchmark.
- Reportwillincludeexplicitper-event MPKI computedwithinrespectivePMUgroups,all-user-thread scope andoriginalNOPcomparison. Rootreportscript syntaxcheckedafteredits.

## Runtime complete: independent result and retention

- All42 cleanE2Erunsvalid(24exploration+18confirmation),180PMUwindowsfullyscheduled;9PEBScaptures313337samples withnoLOST/THROTTLE. Nativecompiler/CFGsuite29passed; staticcoverage12rows replayedexactly.
- Independent6seed selectedbundle summedFE_L2/request reduction3.5121%vsoriginal (t95 1.4761–5.5060%),6.4463%vsNOP(5.6678–7.2184%). ServiceoriginalreductionsMovie4.4928%,Compose3.4823%,Rating2.6148%,eachindividualCIpositive. Code-miss criterion passed.
- E2Epointvsoriginal CPU+.9545%,mean+.1254%,p99+.8868%,RPS+.118%;allCIsincludezero. E2EcriterionNOTpassed. RetiredL1misses+4.642%,instructions+1.410%;usercycle/data-stall reductionvsoriginalunconfirmed. Do notclaim10%E2E.
- Residualmainmiss static-target/matching-LBR-hint sharesMovie52.36/33.98%,Compose48.89/28.98%,Rating30.76/19.17%. Targetlessentryshares15.50/16.38/42.20%. Minimumretiredcycleageproxy0–31accounts53–58%ofmatchingresidualsamples;NOTactualfetchlead orfillproof.
- post_confirmation_complete.json andfinal_environment_audit.json confirmallplatform/schedulerstatesrestored,no campaigncontainers/modules/processes. Failed/supersededbulk cleanedwithrecords;only6selectedIT0/NOPfileskeptasconfirmedcode-missresearchreference;latesttestedpluginretained. Originalinputs/sources/dependenciesuntouched,noNAS.
- Currentread-onlyCPUID7.1EDX0xe4000confirmsPREFETCHIbit14,matchingprioraudit;Linuxcpuinfoflagabsenceisnotasupporttest. OfficialIntelISAdefinitionreferencedinreport.
- Finalreportdocs/class_b_coverage_20260928.md andstatic/effectPNG/SVGgeneratedandvisuallyreviewed. Sourcecodecommitsbfc9da7,5361042,f148b8c,4f8d8f5,fde4243. Gitcompactevidencecollection/commit/pushandrootPTYexitremainadministrativefinalsteps;noexperimentisactive.
