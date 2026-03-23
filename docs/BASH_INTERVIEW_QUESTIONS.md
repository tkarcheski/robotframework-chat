# 100 Bash Interview & Practice Questions

Concise Bash interview/practice questions with short answers, ranging from basics to advanced scripting.

---

## Basics and Fundamentals (1–20)

**1. What is Bash?**
Bash is a Unix shell and command language used as a command interpreter and scripting language on Linux, macOS, and other Unix-like systems.

**2. What is a Bash script and how do you run one?**
A Bash script is a text file with Bash commands; make it executable (`chmod +x script.sh`) and run `./script.sh` or run with `bash script.sh`.

**3. What is the purpose of the shebang `#!/bin/bash`?**
It tells the OS to execute the script with `/bin/bash` rather than the user's default shell.

**4. How do you make a script executable?**
Use `chmod +x script.sh`, then run it as `./script.sh`.

**5. How do you add a comment in Bash?**
Start the line or trailing text with `#`; everything after `#` is ignored by the shell.

**6. How do you define and use a variable?**
`NAME="Alice"` (no spaces around `=`) and reference as `$NAME` or `"${NAME}"`.

**7. How do you read user input into a variable?**
`read -r NAME` then use `$NAME` in the script.

**8. What is the difference between `$0`, `$1`, `$2`, and `$#`?**
`$0` is the script name, `$1`, `$2` are positional arguments, and `$#` is the number of arguments passed.

**9. How do you print to standard output?**
Use `echo "text"` or `printf "format\n" args`.

**10. How do you check the exit code of the last command?**
The special variable `$?` holds the exit status (0 = success, non-zero = error).

**11. What does `set -e` do?**
It makes the script exit immediately if any simple command returns a non-zero status (with some caveats).

**12. What does `set -u` do?**
It treats use of unset variables as an error and causes the script to exit.

**13. What does `set -o pipefail` do?**
It makes a pipeline's exit status be the value of the last non-zero command, preventing silent failures in earlier pipeline stages.

**14. Why is `set -euo pipefail` recommended in many scripts?**
Together they catch many common scripting errors: command failures, unset variables, and hidden pipe errors.

**15. How do you run a script in the current shell instead of a subshell?**
Use `source script.sh` or `. script.sh`.

**16. What's the difference between `source script.sh` and `./script.sh`?**
`source` runs the script in the current shell, affecting its environment; `./script.sh` runs it in a new process with a separate environment.

**17. How do you get the current working directory in a script?**
Use `pwd` or `echo "$PWD"`.

**18. How do you get the current date and time?**
Use `date`, e.g. `date "+%Y-%m-%d %H:%M:%S"`.

**19. How do you exit a script with a specific status code?**
Use `exit 0` for success or `exit 1` (or other non-zero) for failure.

**20. How do you check if a command exists before using it?**
Use `command -v cmd >/dev/null 2>&1` or `type cmd` and check the exit code.

---

## Conditionals, Test, and Control Flow (21–40)

**21. How do you write a simple `if` statement in Bash?**

```bash
if [ "$X" -gt 0 ]; then
  echo "positive"
fi
```

**22. What's the difference between `[` and `[[` in Bash?**
`[` is a POSIX test command; `[[` is a Bash keyword with safer syntax, better pattern matching, and no pathname expansion.

**23. How do you write an `if/elif/else` chain?**

```bash
if cond1; then
  ...
elif cond2; then
  ...
else
  ...
fi
```

**24. How do you test if a file exists?**
`[ -e "$file" ]` is true if the file (of any type) exists.

**25. How do you test if a file is a regular file vs directory?**
`[ -f "$file" ]` for regular file, `[ -d "$dir" ]` for directory.

**26. How do you test if a string is empty or non-empty?**
`[ -z "$str" ]` is true if empty, `[ -n "$str" ]` is true if non-empty.

**27. What does `[ -z "" ] && echo 0 || echo 1` output?**
The test is true (empty string), so it prints `0` (but be wary: this pattern can be surprising with command failures).

**28. How do you compare two integers in Bash?**
Use `-eq`, `-ne`, `-lt`, `-le`, `-gt`, `-ge`, e.g. `[ "$a" -gt "$b" ]`.

**29. How do you compare strings in Bash?**
Use `=` or `!=` inside `[ ]`, e.g. `[ "$a" = "$b" ]`; with `[[` you can also use `==` and pattern matching.

**30. How do you write a `for` loop over arguments?**

```bash
for arg in "$@"; do
  echo "$arg"
done
```

**31. How do you write a C-style `for` loop in Bash?**

```bash
for ((i=0; i<10; i++)); do
  echo "$i"
done
```

**32. How do you write a `while` loop that reads lines from a file?**

```bash
while IFS= read -r line; do
  echo "$line"
done < file.txt
```

**33. How do you write a `case` statement?**

```bash
case "$var" in
  start) echo "start";;
  stop)  echo "stop";;
  *)     echo "unknown";;
esac
```

**34. What is the exit status of a `while` or `for` loop?**
It is the exit status of the last executed command in the loop body or 0 if the loop never ran and the condition didn't fail with an error.

**35. What's the difference between `cmd1 && cmd2` and `cmd1 || cmd2`?**
`cmd1 && cmd2` runs `cmd2` only if `cmd1` succeeds; `cmd1 || cmd2` runs `cmd2` only if `cmd1` fails.

**36. What does `cmd1 && cmd2 || cmd3` mean?**
It runs `cmd2` if `cmd1` succeeds, otherwise runs `cmd3`; but if `cmd2` fails, `cmd3` will also run, so parentheses may be needed.

**37. How do you use the ternary-like pattern `[ cond ] && a || b` safely?**
Ensure `a` cannot fail with a non-zero status; otherwise use an explicit `if` instead.

**38. How do you check multiple conditions (AND/OR) in `[[ ... ]]`?**
Use `&&` for AND and `||` for OR, e.g. `[[ "$x" -gt 0 && "$x" -lt 10 ]]`.

**39. How do you negate a test?**
Prefix the test with `!`, e.g. `if ! command; then ... fi` or `[ ! -f "$file" ]`.

**40. How do you use a `select` loop for a simple menu?**

```bash
select opt in start stop quit; do
  echo "You chose $opt"
  break
done
```

---

## Variables, Parameters, and Quoting (41–60)

**41. What are the two main types of variables in Bash?**
Shell variables and environment variables; environment variables are exported to child processes.

**42. How do you export a variable so child processes can see it?**
`export NAME=value` or `NAME=value; export NAME`.

**43. Why is quoting variables `"${VAR}"` important?**
It prevents word splitting and pathname expansion when VAR contains spaces or special characters, avoiding bugs and security issues.

**44. What is command substitution and how is it done?**
Use `$(command)` to capture the output of a command into a variable: `OUT=$(ls)`.

**45. Why is `$(cmd)` preferred over backticks `` `cmd` ``?**
It's easier to nest, more readable, and behaves more consistently across shells.

**46. What does `$@` represent, and how is it different from `$*`?**
`$@` expands to all arguments as separate words (preserving boundaries when quoted), while `$*` joins them into a single word when quoted.

**47. What does `$#` represent?**
The number of positional parameters passed to the script or function.

**48. What does `$?` represent?**
The exit code of the last command executed.

**49. What does `$$` represent?**
The process ID (PID) of the current shell.

**50. What does `$!` represent?**
The PID of the most recently executed background job.

**51. How do you substitute a default value if a variable is unset or empty?**
`${VAR:-default}` returns VAR if set and non-empty, otherwise `default`.

**52. How do you assign a default value to a variable if it's unset?**
`${VAR:=default}` assigns `default` to VAR if it's unset or null.

**53. How do you get the length of a string variable?**
`${#VAR}` expands to the length of VAR.

**54. How do you extract a substring from a variable?**
`${VAR:offset:length}`, e.g. `${VAR:2:3}`.

**55. How do you perform a simple search-and-replace on a variable value?**
`${VAR/old/new}` replaces the first occurrence; `${VAR//old/new}` replaces all.

**56. What is array syntax in Bash?**
Declare with `arr=(a b c)`, access with `${arr[0]}`, all elements via `"${arr[@]}"`.

**57. How do you append to a Bash array?**
`arr+=("new")`.

**58. How do you get the number of elements in a Bash array?**
`${#arr[@]}`.

**59. What is the difference between single and double quotes?**
Single quotes prevent expansion (literal text); double quotes allow variable and command substitution but still prevent word splitting and globbing (except for some cases).

**60. How do you escape a single quote inside a single-quoted string?**
Close the string, escape the quote, and reopen: `'It'\''s time'`.

---

## I/O, Pipes, Redirection, and Processes (61–80)

**61. What is a pipeline in Bash?**
`cmd1 | cmd2` connects stdout of `cmd1` to stdin of `cmd2`.

**62. What is the difference between a pipe and redirection?**
A pipe passes the output of one process directly to another; redirection sends output to or from files or other descriptors.

**63. How do you redirect stdout to a file, overwriting vs appending?**
Use `>` to overwrite (`cmd > file`) and `>>` to append (`cmd >> file`).

**64. How do you redirect stderr to a file?**
`cmd 2>err.log` overwrites, `cmd 2>>err.log` appends.

**65. How do you redirect both stdout and stderr to the same file?**
`cmd >out.log 2>&1` or in Bash `cmd &>out.log`.

**66. How do you run a command in the background?**
Append `&` at the end of the command, e.g. `long_task &`.

**67. How do you list running jobs in the current shell?**
Use the `jobs` builtin.

**68. How do you bring a background job to the foreground?**
Use `fg` (optionally with a job spec like `%1`).

**69. How do you send a signal to a process?**
Use `kill -SIGTERM pid` or `kill -9 pid` for SIGKILL; `kill -l` lists signals.

**70. How do you use process substitution in Bash?**
`cmd1 < <(cmd2)` or `cmd3 >(cmd4)` treat command output/input as file-like streams.

**71. How do you use command grouping with `{ ...; }`?**
`{ cmd1; cmd2; } >out` runs commands in the current shell with combined redirection.

**72. How do you run commands in a subshell?**
`( cmd1; cmd2 )` runs them in a subshell; environment changes don't leak back.

**73. How do you count lines in a file using a pipeline?**
`wc -l < file` or `cat file | wc -l` (first is more efficient).

**74. How do you find all `.log` files and delete them?**
`find . -name '*.log' -type f -delete` (careful!).

**75. How do you pass the output of one command as arguments to another?**
Use command substitution `cmd2 $(cmd1)` or `xargs`, e.g. `cmd1 | xargs cmd2`.

**76. What does `!!` do in Bash?**
Repeats the previous command; e.g. `sudo !!` reruns the last command with sudo.

**77. How do you re-run the last `cat` command from history?**
Use `!cat` to execute the most recent command starting with `cat`.

**78. How do you get the last argument of the previous command?**
Use `!$`.

**79. How do you schedule a recurring script using cron?**
Edit crontab with `crontab -e` and add a line like `*/5 * * * * /path/script.sh >>/var/log/script.log 2>&1`.

**80. Why should cron jobs usually redirect output?**
To avoid filling mail or logs with default output; redirect stdout and stderr to log files.

---

## Functions, Debugging, and Advanced Topics (81–100)

**81. How do you define a function in Bash?**

```bash
myfunc() {
  echo "hi $1"
}
```

or `function myfunc { ...; }`.

**82. How do you return a status code from a function?**
Use `return N` inside the function or the exit status of the last command; capture with `$?`.

**83. How do you return data (not just status) from a function?**
Echo it and capture with command substitution: `val=$(myfunc)`.

**84. What does `trap` do in Bash scripts?**
It registers handlers to run when the shell receives signals or certain events, e.g. cleanup on EXIT or INT.

**85. Give an example of using `trap` for cleanup.**

```bash
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
```

Ensures the temp file is removed when the script exits.

**86. How do you enable execution tracing for debugging?**
Run the script with `bash -x script.sh` or inside use `set -x` to start tracing and `set +x` to stop.

**87. What's the difference between `"` and `` ` `` in prompts like PS1?**
PS1 is expanded by Bash each time it displays the prompt using standard expansion rules; backticks are command substitution, but `\[` `\]` are used to mark non-printing characters for proper line editing.

**88. What are builtins and how do they differ from external commands?**
Builtins (like `cd`, `echo`, `kill`) run inside the shell process and don't require a fork/exec; external commands are separate executables on disk.

**89. How do you ensure a script fails fast when a pipeline command fails?**
Use `set -o pipefail` in combination with `set -e` so that the pipeline's non-zero status causes the script to exit.

**90. What's a here-document and how do you use it?**

```bash
cat <<EOF
line1
line2
EOF
```

**91. What's a here-string and how do you use it?**
`cmd <<< "$text"` feeds the string as stdin to `cmd` in Bash.

**92. How do you safely iterate over files with spaces in their names?**
Use `find ... -print0 | while IFS= read -r -d '' f; do ...; done` or `for f in ./*; do ...; done` with proper quoting.

**93. Why is `for f in $(ls)` considered bad style?**
Word splitting on whitespace and globbing can break filenames with spaces, newlines, or special characters; it's fragile.

**94. How do you check if a variable is set (even if empty)?**
Use parameter expansion or `[[ -v VAR ]]` in modern Bash.

**95. How do you test if a script is being sourced or executed directly?**
Compare `$0` and `$BASH_SOURCE`: `if [ "$0" != "$BASH_SOURCE" ]`, it is sourced.

**96. How do you limit a script to run only in Bash (not sh)?**
Use `#!/usr/bin/env bash` or `#!/bin/bash` and Bash-specific features (`[[ ]]`, arrays, etc.).

**97. Why is Bash considered weakly typed?**
Variables are untyped strings by default; Bash does not enforce data types and converts values as needed.

**98. How do you enable strict mode in Bash?**

```bash
set -euo pipefail
IFS=$'\n\t'
```

to catch errors and avoid unintended splitting.

**99. How do you write a one-liner to find and kill a process by name?**
For example: `pkill -f "pattern"` or `ps aux | grep pattern | awk '{print $2}' | xargs kill` (use carefully).

**100. What are common safety best practices for production Bash scripts?**
Use `set -euo pipefail`, quote all variables, check exit codes, log output, avoid parsing `ls`, and prefer simple, readable code over clever one-liners.
