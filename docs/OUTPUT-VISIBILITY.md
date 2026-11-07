# Output visibility

Use the calculation's scientific stdout stream for timely SCF progress. An empty
or delayed OSZICAR does not by itself mean that VASP has stopped. No runner
buffering setting is enabled by this document, and the real-VASP qualification
below has **not been run**.

## Why the files can disagree

The inspected VASP 6.6.1 CPU build uses GNU Fortran 16.1.0, its libgfortran
runtime, and Open MPI 5.0.9. OSZICAR, OUTCAR and vasprun.xml are sequential
formatted regular files. GNU Fortran buffers regular-file output. The inspected
electronic loops do not actively flush OSZICAR and OUTCAR after each SCF step;
explicit progress-file flushes occur at ionic boundaries, with XML also flushed
at an ionic calculation boundary. The runtime can release data earlier when a
buffer fills or a file closes. A long SCF can therefore leave OSZICAR empty even
though VASP has written electronic-step records to its runtime buffer.

The observed MPI forwarding path connects the rank's preconnected stdout to a
terminal, then forwards it to the calculation's stdout log. GNU Fortran does
not buffer terminals and pipes as it does regular files. This path showed
complete DAV records ahead of OSZICAR and OUTCAR. That observation and the source
structure strongly support buffering; they are not a controlled comparison of
runtime settings or a guarantee about every MPI forwarding configuration.

Different milestones also matter. OUTCAR can describe ionic evaluation 4 in
progress while OSZICAR's latest completed ionic summary is 3. That alone is not
a contradiction. Compare matching electronic or completed ionic records before
attributing the difference to buffering. Visibility is also distinct from
durability: flushing a language-runtime buffer does not guarantee persistence
through a power failure.

Local source references, without reproduced source text: VASP `src/main.F`,
`src/electron.F`, `src/electron_all.F`, `src/xml.F`, `src/fileio.F` and
`src/lib/diolib.F`. Build references: `provenance/build-info.txt` and
`config/makefile.include.macos-arm64`.

## Recommended progress source

The qualified CMW source already uses the most advanced usable complete-row
stream from OSZICAR and declared scientific stdout. It keeps that source-local
progress separate from the portion checked against OUTCAR. Empty OSZICAR must
not hide usable stdout. OUTCAR remains useful for settings, forces, stress and
native context; stdout cannot expose quantities VASP has not yet produced.

Bind the calculation's actual stdout file, not the Jobs operational log. CMW's
automatic binding recognizes supported managed runner routes; an arbitrary
shell command must not be assumed to have that binding. Source capability does
not establish which CMW version or source declaration a deployed job uses.
No CMW change or deployment is part of this investigation.

CMW references: `src/cmw/progress/vasp.py`,
`src/cmw/jobs/location_resolvers.py`, `docs/cmw-jobs-progress.md`,
`tests/progress/test_vasp_crosscheck.py` and `tests/nodes/test_vasp_stdout.py`.

## Runtime settings remain opt-in and unqualified

`GFORTRAN_UNBUFFERED_ALL=1` is a possible future per-launch experiment, not a
recommended default. It affects all Fortran units, including large formatted
CHGCAR/XML writes and direct-access unformatted WAVECAR writes. More frequent
small writes can increase overhead; the effect on total runtime and restart
output must be measured rather than inferred from progress-file latency.

`GFORTRAN_UNBUFFERED_PRECONNECTED=1` affects preconnected stdout/stderr, not
OSZICAR, OUTCAR or XML. It is a useful negative control for the external-file
hypothesis, and may be redundant when MPI already supplies a terminal or pipe.
These GNU controls are not interchangeable with another compiler's runtime
settings. Neither setting is currently imposed by the runner.

The shell route that sources `scripts/environment.sh` and invokes mpirun
directly bypasses `scripts/launch.py`. A setting implemented only in launch.py
will not reach that route. The managed runner currently copies the parent
environment into the child environment; a future experiment must verify the
effective values in the ranks, not merely the launching shell. Open MPI can
explicitly export named variables with `-x`.

Any later runner option must start from current main and preserve PR #2's
ownership, session, signal, timeout and hold behavior. Keep
`config/cmw-test-revision.txt` unchanged until the separate CMW deployment-candidate
qualification after issue #22. Re-run the existing ownership, drainage,
controlled-suspension, API-compatibility and persistent-hold tests under each
supported setting, and add synthetic assertions for the shell-to-child
environment path. No extra wrapper, process group or signal path is needed.

Runner references: `scripts/environment.sh`, `scripts/launch.py`,
`scripts/run_vasp.py` and `.github/workflows/runner-ownership.yml`.

## Real-VASP qualification: not yet run

This is deferred until **post-cutover**, on the Mini, and only if live
OSZICAR/OUTCAR files are actually needed beyond the timely stdout display.
It requires separate authorization; this document does not initiate it.

1. Check processes and load first. Defer if the machine is busy. Use fresh
   scratch directories outside repositories and production runs, one MPI rank
   initially and at most two. Keep licensed inputs, outputs and raw logs private.
2. Use a small licensed Si validation case with identical inputs and starting
   restart state in every condition. Choose tight EDIFF, NELMIN around 15 and
   sufficient NELM to observe multiple SCF steps. Enable normal XML output and
   explicitly enable LWAVE and LCHARG. Keep the executable, thread limits,
   storage, MPI placement and scientific settings fixed.
3. Compare three repetitions each of the baseline with buffering overrides
   unset, ALL=1, and PRECONNECTED=1 with ALL unset. Leave buffer-size overrides
   unset. Interleave conditions to reduce cache/order bias and verify effective
   rank environments. Record each condition separately.
4. Poll file sizes, mtimes and complete appended records every second. Match
   step identities across streams and measure relative visibility lag against
   the timely stdout record. Record median, p95 and maximum lag; retain partial
   records as pending. This measures relative visibility, not an instrumented
   timestamp of the underlying Fortran write.
5. Record wall, user and system time, output sizes and available I/O counters.
   Report wall time as mean and sample standard deviation across repetitions.
   Measure final-SCF-to-exit time separately, and use matched output-on/off
   runs to estimate incremental WAVECAR/CHGCAR output cost. Neither system CPU
   time nor finalization duration is pure I/O time. Exact I/O timing would need
   separately approved instrumentation; label estimates honestly.
6. Compare completed scientific results, convergence histories, output
   completeness and restart readability with the baseline. Agree numerical
   tolerances before testing. A small case establishes behavior, not overhead
   for production-sized WAVECAR/CHGCAR/XML files; qualify a bounded larger-output
   case before considering a general default.
7. Accept a setting only after it provides complete per-step visibility within
   the agreed polling tolerance, preserves output/scientific results and has
   acceptable measured overhead. Recheck the synthetic supervision matrix for
   any runner change. Until then, retain existing launch behavior and use stdout.

No performance figures or numerical qualification are claimed for these settings.
This repository distributes independent tooling and documentation, not VASP
source, source-bearing patches, binaries or potential datasets.

## Runtime documentation

- [GNU Fortran: data consistency and durability](https://gcc.gnu.org/onlinedocs/gfortran/Data-consistency-and-durability.html)
- [GNU Fortran: GFORTRAN_UNBUFFERED_ALL](https://gcc.gnu.org/onlinedocs/gfortran/GFORTRAN_005fUNBUFFERED_005fALL.html)
- [GNU Fortran: GFORTRAN_UNBUFFERED_PRECONNECTED](https://gcc.gnu.org/onlinedocs/gfortran/GFORTRAN_005fUNBUFFERED_005fPRECONNECTED.html)
- [Open MPI 5.0.9: mpirun](https://docs.open-mpi.org/en/v5.0.9/man-openmpi/man1/mpirun.1.html)
