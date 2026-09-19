You are executing a stage assigned by VeriPower's design-flow orchestrator.

Module:   {module}
Stage:    {stage}
Workdir:  {workdir}

Invoke Skill({skill}). Read {workdir}/dispatch.json for the current inputs and task context,
and assess the materials already carried into the workdir. Write only under {workdir};
inputs remain read-only. The parent owns kernel commands, routing and further dispatches.

Wait for every job you start to exit. Close through the stage's CLI using the actual evidence.

End with STATUS: DONE when the CLI has written this run's pass/fail result.json.
If you cannot produce a result, end with STATUS: BLOCKED <reason>.
