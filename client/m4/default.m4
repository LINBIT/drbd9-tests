m4_divert(-1)
m4_define(`m4_default', `m4_ifelse(`$1', `', `$2', ``$1'')')
divert`'dnl
