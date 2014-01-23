m4_divert(`-1')
# m4_join(sep, args) - join each non-empty ARG into a single
# string, with each element separated by SEP
m4_define(`m4_join',
`m4_ifelse(`$#', `2', ``$2'',
  `m4_ifelse(`$2', `', `', ``$2'_')$0(`$1', m4_shift(m4_shift($@)))')')
m4_define(`_m4_join',
`m4_ifelse(`$#$2', `2', `',
  `m4_ifelse(`$2', `', `', ``$1$2'')$0(`$1', m4_shift(m4_shift($@)))')')
# m4_joinall(sep, args) - join each ARG, including empty ones,
# into a single string, with each element separated by SEP
m4_define(`m4_joinall', ``$2'_$0(`$1', m4_shift($@))')
m4_define(`_m4_joinall',
`m4_ifelse(`$#', `2', `', ``$1$3'$0(`$1', m4_shift(m4_shift($@)))')')
m4_divert`'m4_dnl
