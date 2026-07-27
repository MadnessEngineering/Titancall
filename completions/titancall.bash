# bash completion for titancall — delegates to `titancall __complete` so candidates
# (titans, devices, aliases, buckets) stay live. Source this, or drop it in a
# bash-completion.d dir. install.sh wires it up automatically.
_titancall() {
  local cur ctx cands IFS=$'\n'
  cur="${COMP_WORDS[COMP_CWORD]}"
  ctx=("${COMP_WORDS[@]:1:COMP_CWORD-1}")        # words between `titancall` and the cursor
  cands=$(titancall __complete "${ctx[@]}" 2>/dev/null)
  COMPREPLY=($(compgen -W "$cands" -- "$cur"))    # IFS=newline preserves multi-word device names
}
complete -F _titancall titancall
