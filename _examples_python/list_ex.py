"""
https://docs.python.org/3/glossary.html#term-sequence
 sequence
An iterable which supports efficient element access using integer indices via the __getitem__() 
pecial method and defines a __len__() method that returns the length of the sequence. Some 
built-in sequence types are list, str, tuple, and bytes. Note that dict also supports 
__getitem__() and __len__(), but is considered a mapping rather than a sequence because the
 lookups use arbitrary immutable keys rather than integers.

The collections.abc.Sequence abstract base class defines a much richer interface that goes beyond
 just __getitem__() and __len__(), adding count(), index(), __contains__(), and __reversed__(). 
 Types that implement this expanded interface can be registered explicitly using register(). 
 """

 # you know for later when you actually make some examples for lists or maybe tuples.