m4_include(`quote.m4')m4_dnl
m4_include(`array.m4')m4_dnl
The following macros define array access functions for setting or
getting array elements:

  m4_define_array(`DISK1')
  m4_define_array(`DISK2')
  m4_define_array(`DISK3')
  m4_next_array(`DISK')

Array elements can be set with:

  DISK1(`foo', `/dev/scratch/foo1')
  DISK2(`foo', `/dev/scratch/foo2')
  DISK3(`foo', `/dev/scratch/foo3')

A specific array element can be retrieved with:

  DISK2(`foo')  ==>  /dev/scratch/foo2

The "next" array element from DISKn can be retrieved with:

  DISK(`foo')  ==>  /dev/scratch/foo1
  DISK(`foo')  ==>  /dev/scratch/foo2
  DISK(`foo')  ==>  /dev/scratch/foo3
  DISK(`foo')  ==>  
