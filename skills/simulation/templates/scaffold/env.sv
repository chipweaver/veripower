// Environment for {{MODULE}}.
// Generated from scaffold-spec.json. Typically nothing to fill — fully assembled.
class {{MODULE}}_env extends uvm_env;
  `uvm_component_utils({{MODULE}}_env)

{{AGENT_DECLARATIONS}}
  {{MODULE}}_{{RM_NAME}}  m_rm;
  {{MODULE}}_{{SB_NAME}} m_scoreboard;

  function new(string name = "{{MODULE}}_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
{{AGENT_CREATES}}
    m_rm = {{MODULE}}_{{RM_NAME}}::type_id::create("m_rm", this);
    m_scoreboard = {{MODULE}}_{{SB_NAME}}::type_id::create("m_scoreboard", this);
  endfunction

  function void connect_phase(uvm_phase phase);
{{AGENT_CONNECTS}}
  endfunction
endclass
