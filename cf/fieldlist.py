from .functions import (_DEPRECATION_ERROR,
                        _DEPRECATION_ERROR_KWARGS,
                        _DEPRECATION_ERROR_METHOD,
                        _DEPRECATION_ERROR_ATTRIBUTE,
                        _DEPRECATION_ERROR_DICT,
                        _DEPRECATION_ERROR_SEQUENCE)


class FieldList(list):
    '''An ordered sequence of fields.

Each element of a field list is a field construct.

A field list supports the python list-like operations (such as
indexing and methods like `!append`).

>>> fl = cf.FieldList()
>>> len(fl)
0
>>> f
<CF Field: air_temperaturetime(12), latitude(73), longitude(96) K>
>>> fl = cf.FieldList(f)
>>> len(fl)
1
>>> fl = cf.FieldList([f, f])
>>> len(fl)
2
>>> fl = cf.FieldList(cf.FieldList([f] * 3))
>>> len(fl)
3
>>> len(fl + fl)
6

These methods provide functionality similar to that of a
:ref:`built-in list <python:tut-morelists>`. The main difference is
that when a field element needs to be assesed for equality its
`~cf.Field.equals` method is used, rather than the ``==`` operator.

    '''   
    def __init__(self, fields=None):
        '''**Initialization**

    :Parameters:

        fields: (sequence of) `Field`, optional
             Create a new field list with these fields.

        '''
        if fields is not None:
            if getattr(fields, 'construct_type', None) == 'field':
                self.append(fields)
            else:
                self.extend(fields)         


    def __call__(self, *identities):
        '''Alias for `cf.FieldList.filter_by_identity`.

        '''        
        return self.filter_by_identity(*identities)

    
    def __repr__(self):
        '''Called by the `repr` built-in function.

    x.__repr__() <==> repr(x)

        '''
        
        out = [repr(f) for f in self]
        out = ',\n '.join(out)
        return '['+out+']'

    
    # ----------------------------------------------------------------
    # Overloaded list methods
    # ----------------------------------------------------------------
    def __add__(self, x):
        '''Called to implement evaluation of f + x

    f.__add__(x) <==> f + x
    
    :Returns:
    
        `FieldList`
    
    **Examples:**
    
    >>> h = f + g
    >>> f += g

        '''
        return type(self)(list.__add__(self, x))


    def __mul__(self, x):
        '''Called to implement evaluation of f * x

    f.__mul__(x) <==> f * x
    
    :Returns:
    
        `FieldList`
    
    **Examples:**
    
    >>> h = f * 2
    >>> f *= 2

        '''
        return type(self)(list.__mul__(self, x))


    def __getslice__(self, i, j):
        '''Called to implement evaluation of f[i:j]

    f.__getslice__(i, j) <==> f[i:j]
    
    :Returns:
    
        `FieldList`
    
    **Examples:**
    
    >>> g = f[0:1]
    >>> g = f[1:-4]
    >>> g = f[:1]
    >>> g = f[1:]

        '''
        return type(self)(list.__getslice__(self, i, j))


    def __getitem__(self, index):
        '''Called to implement evaluation of f[index]

    f.__getitem_(index) <==> f[index]
    
    :Returns:
    
        `Field` or `FieldList`
            If *index* is an integer then a field construct is
            returned. If *index* is a slice then a field list is returned,
            which may be empty.
    
    **Examples:**
    
    >>> g = f[0]
    >>> g = f[-1:-4:-1]
    >>> g = f[2:2:2]

        '''
        out = list.__getitem__(self, index)

        if isinstance(out, list):
            return type(self)(out)

        return out

    # ???
    __len__     = list.__len__
    __setitem__ = list.__setitem__    
    append      = list.append
    extend      = list.extend
    insert      = list.insert
    pop         = list.pop
    reverse     = list.reverse
    sort        = list.sort

    def __contains__(self, y):
        '''Called to implement membership test operators.

    x.__contains__(y) <==> y in x
    
    Each field in the field list is compared with the field's
    `~cf.Field.equals` method, as aopposed to the ``==`` operator.
    
    Note that ``y in fl`` is equivalent to ``any(f.equals(y) for f in fl)``.

        '''
        for f in self:
            if f.equals(y):
                return True
        #--- End: for
            
        return False


    # ----------------------------------------------------------------
    # Methods
    # ----------------------------------------------------------------
    def close(self):
        '''Close all files referenced by each field.

    Note that a closed file will be automatically reopened if its
    contents are subsequently required.
    
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> f.close()

        '''
        for f in self:
            f.close()


    def count(self, value):
        '''Return number of occurrences of value

    Each field in the field list is compared with the field's
    `~cf.Field.equals` method, as opposed to the ``==`` operator.
    
    Note that ``fl.count(value)`` is equivalent to
    ``sum(f.equals(value) for f in fl)``.
    
    .. seealso:: `cf.Field.equals`, `list.count`
    
    **Examples:**
    
    >>> f = cf.FieldList([a, b, c, a])
    >>> f.count(a)
    2
    >>> f.count(b)
    1
    >>> f.count(a+1)
    0

        '''
        return len([None for f in self if f.equals(value)])


    def index(self, value, start=0, stop=None):
        '''Return first index of value.

    Each field in the field list is compared with the field's
    `~cf.Field.equals` method, as aopposed to the ``==`` operator.
    
    It is an error if there is no such field.
    
    .. seealso:: `list.index`
    
        '''      
        if start < 0:
            start = len(self) + start

        if stop is None:
            stop = len(self)
        elif stop < 0:
            stop = len(self) + stop

        for i, f in enumerate(self[start:stop]):
            if f.equals(value):
               return i + start
        #--- End: for

        raise ValueError(
            "{0!r} is not in {1}".format(value, self.__class__.__name__))


    def remove(self, value):
        '''Remove first occurrence of value.

    Each field in the field list is compared with its
    `~cf.Field.equals` method, as opposed to the ``==`` operator.
    
    .. seealso:: `list.remove`

        '''
        for i, f in enumerate(self):
            if f.equals(value):
                del self[i]
                return
        #--- End: for
        
        raise ValueError(
            "{0}.remove(x): x not in {0}".format(self.__class__.__name__))


    def sort(self, key=None, reverse=False):
        '''Sort of the field list in place.

    By default the field list is sorted by the identities of its field
    construct elements.

    The sort is stable.
    
    .. versionadded:: 1.0.4
    
    .. seealso:: `reverse`
    
    :Parameters:
    
        key: function, optional
            Specify a function of one argument that is used to extract
            a comparison key from each field construct. By default the
            field list is sorted by field identity, i.e. the default
            value of *key* is ``lambda f: f.identity()``.
    
        reverse: `bool`, optional
            If set to `True`, then the field list elements are sorted
            as if each comparison were reversed.
    
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> fl
    [<CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
     <CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>,
     <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>,
     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>]
    >>> fl.sort()
    >>> fl
    [<CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>,
     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
     <CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>]
    >>> fl.sort(reverse=True)
    >>> fl
    [<CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>,
     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
     <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>]
    
    >>> [f.datum(0) for f in fl]
    [masked,
     -0.12850454449653625,
     -0.12850454449653625,
     236.51275634765625]
    >>> fl.sort(key=lambda f: f.datum(0), reverse=True)
    >>> [f.datum(0) for f in fl]
    [masked,
     236.51275634765625,
     -0.12850454449653625,
     -0.12850454449653625]
    
    >>> from operator import attrgetter
    >>> [f.long_name for f in fl]
    ['Meridional Overturning Streamfunction',
     'U COMPNT OF WIND ON PRESSURE LEVELS',
     'U COMPNT OF WIND ON PRESSURE LEVELS',
     'air_temperature']
    >>> fl.sort(key=attrgetter('long_name'))
    >>> [f.long_name for f in fl]
    ['air_temperature',
     'Meridional Overturning Streamfunction',
     'U COMPNT OF WIND ON PRESSURE LEVELS',
     'U COMPNT OF WIND ON PRESSURE LEVELS']

        '''
        if key is None:
            key = lambda f: f.identity()
            
        return super().sort(key=key, reverse=reverse)



    def _deepcopy__(self, memo):
        '''Called by the `copy.deepcopy` standard library function.

        '''
        return self.copy()

    
    def concatenate(self, axis=0, _preserve=True):
        '''Join the sequence of fields together.

    This is different to `cf.aggregate` because it does not account
    for all metadata. For example, it assumes that the axis order is
    the same in each field.
    
    .. versionadded:: 1.0
    
    .. seealso:: `cf.aggregate`, `Data.concatenate`
    
    :Parameters:
    
        axis: `int`, optional
            TODO

    :Returns:
    
        `Field`
            TODO

        '''
        return self[0].concatenate(self, axis=axis, _preserve=_preserve)


    def copy(self, data=True):
        '''Return a deep copy.
    
    ``f.copy()`` is equivalent to ``copy.deepcopy(f)``.
    
    :Returns:
    
            The deep copy.
    
    **Examples:**
    
    >>> g = f.copy()
    >>> g is f
    False
    >>> f.equals(g)
    True
    >>> import copy
    >>> h = copy.deepcopy(f)
    >>> h is f
    False
    >>> f.equals(g)
    True

        '''
        return type(self)([f.copy(data=data) for f in self])

    
    def equals(self, other, rtol=None, atol=None, verbose=False,
               ignore_data_type=False, ignore_fill_value=False,
               ignore_properties=(), ignore_compression=False,
               ignore_type=False, ignore=(), traceback=False,
               unordered=False):
        '''Whether two field lists are the same.

    Equality requires the two field lists to have the same length and
    for the the field construct elements to be equal pair-wise, using
    their `~cf.Field.equals` methods.
    
    Any type of object may be tested but, in general, equality is only
    possible with another field list, or a subclass of one. See the
    *ignore_type* parameter.
    
    Equality is between teo field constructs is strict by
    default. This means that for two field constructs to be considered
    equal they must have corresponding metadata constructs and for
    each pair of constructs:
    
    * the same descriptive properties must be present, with the same
      values and data types, and vector-valued properties must also
      have same the size and be element-wise equal (see the
      *ignore_properties* and *ignore_data_type* parameters), and
    
    ..
    
    * if there are data arrays then they must have same shape and data
      type, the same missing data mask, and be element-wise equal (see
      the *ignore_data_type* parameter).
    
    Two real numbers ``x`` and ``y`` are considered equal if
    ``|x-y|<=atol+rtol|y|``, where ``atol`` (the tolerance on absolute
    differences) and ``rtol`` (the tolerance on relative differences)
    are positive, typically very small numbers. See the *atol* and
    *rtol* parameters.
    
    If data arrays are compressed then the compression type and the
    underlying compressed arrays must be the same, as well as the
    arrays in their uncompressed forms. See the *ignore_compression*
    parameter.
    
    NetCDF elements, such as netCDF variable and dimension names, do
    not constitute part of the CF data model and so are not checked on
    any construct.
    
    :Parameters:
        other: 
            The object to compare for equality.
    
        atol: float, optional
            The tolerance on absolute differences between real
            numbers. The default value is set by the `cfdm.ATOL`
            function.
            
        rtol: float, optional
            The tolerance on relative differences between real
            numbers. The default value is set by the `cfdm.RTOL`
            function.
    
        ignore_fill_value: `bool`, optional
            If `True` then the "_FillValue" and "missing_value"
            properties are omitted from the comparison, for the field
            construct and metadata constructs.
    
        verbose: `bool`, optional
            If `True` then print information about differences that lead
            to inequality.
    
        ignore_properties: sequence of `str`, optional
            The names of properties of the field construct (not the
            metadata constructs) to omit from the comparison. Note
            that the "Conventions" property is always omitted by
            default.
    
        ignore_data_type: `bool`, optional
            If `True` then ignore the data types in all numerical
            comparisons. By default different numerical data types
            imply inequality, regardless of whether the elements are
            within the tolerance for equality.
    
        ignore_compression: `bool`, optional
            If `True` then any compression applied to underlying arrays
            is ignored and only uncompressed arrays are tested for
            equality. By default the compression type and, if
            applicable, the underlying compressed arrays must be the
            same, as well as the arrays in their uncompressed forms
    
        ignore_type: `bool`, optional
            Any type of object may be tested but, in general, equality
            is only possible with another field list, or a subclass of
            one. If *ignore_type* is True then
            ``FieldList(source=other)`` is tested, rather than the
            ``other`` defined by the *other* parameter.

        unordered: `bool`, optional
            TODO
    
    :Returns: 
      
        `bool`
            Whether the two field lists are equal.
    
    **Examples:**
    
    >>> fl.equals(fl)
    True
    >>> fl.equals(fl.copy())
    True
    >>> fl.equals(fl[:])
    True
    >>> fl.equals('not a FieldList instance')
    False

        '''
        if traceback:
            _DEPRECATION_ERROR_KWARGS(self, 'equals', traceback=True) # pragma: no cover
            
        if ignore:
            _DEPRECATION_ERROR_KWARGS(self, 'equals', {'ignore': ignore},
                                      "Use keyword 'ignore_properties' instead.") # pragma: no cover
            
        # Check for object identity
        if self is other:
            return True

        # Check that each object is of compatible type
        if ignore_type:
            if not isinstance(other, self.__class__):
                other = type(self)(source=other, copy=False)
        elif not isinstance(other, self.__class__):
            if verbose:
                print("{0}: Incompatible type: {1}".format(
		    self.__class__.__name__, other.__class__.__name__)) # pragma: no cover
            return False

        # Check that there are equal numbers of fields
        len_self = len(self)
        if len_self != len(other): 
            if verbose:
                print("{0}: Different numbers of field construct: {1}, {2}".format(
		    self.__class__.__name__,
		    len_self, len(other))) # pragma: no cover
            return False

        if not unordered or len_self == 1:
       	    # ----------------------------------------------------
    	    # Check the lists pair-wise
    	    # ----------------------------------------------------
    	    for i, (f, g) in enumerate(zip(self, other)):
    	        if not f.equals(g, rtol=rtol, atol=atol,
                                ignore_fill_value=ignore_fill_value,
                                ignore_properties=ignore_properties,
                                ignore_compression=ignore_compression,
                                ignore_data_type=ignore_data_type,
                                ignore_type=ignore_type,
                                verbose=verbose):
                    if verbose:
                        print("{0}: Different field constructs at element {1}: {2!r}, {3!r}".format(
    			    self.__class__.__name__, i, f, g)) # pragma: no cover
                    return False
        else:
    	    # ----------------------------------------------------
    	    # Check the lists set-wise
    	    # ----------------------------------------------------
    	    # Group the variables by identity
            self_identity = {}
            for f in self:
                self_identity.setdefault(f.identity(), []).append(f)

            other_identity = {}
            for f in other:
                other_identity.setdefault(f.identity(), []).append(f)

    	    # Check that there are the same identities
            if set(self_identity) != set(other_identity):
    	        if verbose:
                    print("{}: Different sets of identities: {}, {}".format(
    			self.__class__.__name__,
    			set(self_identity),
    			set(other_identity))) # pragma: no cover
    	        return False

            # Check that there are the same number of variables
    	    # for each identity
            for identity, fl in self_identity.items():
    	        gl = other_identity[identity]
    	        if len(fl) != len(gl):
                    if verbose:
                        print("{0}: Different numbers of {1!r} {2}s: {3}, {4}".format(
    			    self.__class__.__name__,
    			    identity,
                            fl[0].__class__.__name__,
    			    len(fl), len(gl))) # pragma: no cover
                    return False
            #--- End: for

    	    # For each identity, check that there are matching pairs
            # of equal fields.
            for identity, fl in self_identity.items():
                gl = other_identity[identity]

                for f in fl:
                    found_match = False
                    for i, g in enumerate(gl):
                        if f.equals(g, rtol=rtol, atol=atol,
                                    ignore_fill_value=ignore_fill_value,
                                    ignore_properties=ignore_properties,
                                    ignore_compression=ignore_compression,
                                    ignore_data_type=ignore_data_type,
                                    ignore_type=ignore_type,
                                    verbose=verbose):
                            found_match = True
                            del gl[i]
                            break
                #--- End: for
                
                if not found_match:
                    if verbose:                        
                        print("{0}: No {1} equal to: {2!r}".format(
    			    self.__class__.__name__, g.__class__.__name__, f)) # pragma: no cover
                    return False
        #--- End: if

        # ------------------------------------------------------------
    	# Still here? Then the field lists are equal
    	# ------------------------------------------------------------
        return True	    


    def filter_by_construct(self, *mode, **constructs):
        '''TODO

        '''    
        return type(self)(f for f in self if f.match_by_construct(*mode, **constructs))

    
    def filter_by_identity(self, *identities):
        '''Select field constructs by identity.

    To find the inverse of the selection, use a list comprehension
    with `~cf.Field.match_by_identity` method of the field
    constucts. For example, to select all field constructs whose
    identity is *not* ``'air_temperature'``:
            
       >>> gl = cf.FieldList(f for f in fl if not f.match_by_identity('air_temperature'))
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `select`, `filter_by_units`, `filter_by_construct`,
                 `filter_by_naxes`, `filter_by_rank`,
                 `filter_by_property`, `cf.Field.match_by_identity`
    
        identities: optional
            Select field constructs. By default all field constructs
            are selected. May be one or more of:
    
              * The identity of a field construct.
    
            A construct identity is specified by a string (e.g.
            ``'air_temperature'``, ``'long_name=Air Temperature',
            ``'ncvar%tas'``, etc.); or a compiled regular expression
            (e.g. ``re.compile('^air_')``) that selects the relevant
            constructs whose identities match via `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            five identities:
    
               >>> x.identities()
               ['air_temperature', 'long_name=Air Temperature', 'foo=bar', 'standard_name=air_temperature', 'ncvar%tas']
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identities* argument.
    
    :Returns:
    
        `FieldList`
            The matching field constructs.
    
    **Examples:**
    
    >>> fl
    [<CF Field: specific_humidity(latitude(73), longitude(96)) 1>,
     <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>]
    >>> fl('air_temperature')
    [<CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>]

        '''       
        return type(self)(f for f in self if f.match_by_identity(*identities))

    
    def filter_by_naxes(self, *naxes):
        '''Select field constructs by property.

    To find the inverse of the selection, use a list comprehension
    with `~cf.Field.match_by_naxes` method of the field constucts. For
    example, to select all field constructs which do *not* have
    3-dimensional data:
            
       >>> gl = cf.FieldList(f for f in fl if not f.match_by_naxes(3))
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `select`, `filter_by_identity`,
                 `filter_by_construct`, `filter_by_property`,
                 `filter_by_rank`, `filter_by_units` :Parameters:
    
        naxes: optional
            Select field constructs whose data spans a particular
            number of domain axis constructs.
    
            A number of domain axis constructs is given by an `int`.
    
            If no numbers are provided then all field constructs are
            selected.
         
    :Returns:
    
        `FieldList`
            The matching field constructs.
    
    **Examples:**
    
    TODO

        '''
        return type(self)(f for f in self if f.match_by_naxes(*naxes))

    
    def filter_by_rank(self, *ranks):
        '''TODO'''
        
        return type(self)(f for f in self if f.match_by_rank(*ranks))

    
    def filter_by_ncvar(self, *rank):
        '''Select field constructs by netCDF variable name.
    
    To find the inverse of the selection, use a list comprehension
    with `~cf.Field.match_by_ncvar` method of the field constucts. For
    example, to select all field constructs which do *not* have a
    netCDF name of 'tas':
            
       >>> gl = cf.FieldList(f for f in fl if not f.match_by_ncvar('tas'))
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `select`, `filter_by_identity`,
                 `filter_by_construct`, `filter_by_naxes`,
                 `filter_by_rank`, `filter_by_units`
    
        ncvars: optional
            Select field constructs. May be one or more:
    
              * The netCDF name of a field construct.
    
            A field construct is selected if it matches any of the
            given names.
    
            A netCDF variable name is specified by a string (e.g.
            ``'tas'``, etc.); a `Query` object
            (e.g. ``cf.eq('tas')``); or a compiled regular expression
            (e.g. ``re.compile('^air_')``) that selects the field
            constructs whose netCDF variable names match via
            `re.search`.
    
            If no netCDF variable names are provided then all field
            are selected.
    
    :Returns:
    
        `FieldList`
            The matching field constructs.
    
    **Examples:**
    
    TODO

        '''     
        return type(self)(f for f in self if f.match_by_ncvar(*ncvars))

    
    def filter_by_property(self, *mode, **properties):
        '''Select field constructs by property.

    To find the inverse of the selection, use a list comprehension
    with `~cf.Field.match_by_property` method of the field
    constucts. For example, to select all field constructs which do
    *not* have a long_name property of 'Air Pressure':
            
       >>> gl = cf.FieldList(f for f in fl if not f.match_by_property(long_name='Air Pressure))
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `select`, `filter_by_identity`,
                 `filter_by_construct`, `filter_by_naxes`,
                 `filter_by_rank`, `filter_by_units`
    
        mode: optional
            Define the behaviour when multiple properties are
            provided.
    
            By default (or if the *mode* parameter is ``'and'``) a
            field construct is selected if it matches all of the given
            properties, but if the *mode* parameter is ``'or'`` then a
            field construct will be selected when at least one of its
            properties matches.
    
        properties: optional
            Select field constructs. May be one or more of:
    
              * The property of a field construct.
    
            By default a field construct is selected if it matches all
            of the given properties, but it may alternatively be
            selected when at least one of its properties matches (see
            the *mode* positional parameter).
    
            A property value is given by a keyword parameter of the
            property name. The value may be a scalar or vector
            (e.g. ``'air_temperature'``, ``4``, ``['foo', 'bar']``);
            or a compiled regular expression
            (e.g. ``re.compile('^ocean')``), for which all constructs
            whose methods match (via `re.search`) are selected.
            
    :Returns:
    
        `FieldList`
            The matching field constructs.
    
    **Examples:**
    
    TODO

        '''
        return type(self)(f for f in self if f.match_by_property(*mode, **properties))

    
    def filter_by_units(self, *units, exact=True):
        '''Select field constructs by units.

    To find the inverse of the selection, use a list comprehension
    with `~cf.Field.match_by_units` method of the field constucts. For
    example, to select all field constructs whose units are *not*
    ``'km'``:
            
       >>> gl = cf.FieldList(f for f in fl if not f.match_by_units('km'))
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `select`, `filter_by_identity`,
                 `filter_by_construct`, `filter_by_naxes`,
                 `filter_by_rank`, `filter_by_property`
    
        units: optional
            Select field constructs. By default all field constructs
            are selected. May be one or more of:
    
              * The units of a field construct.
    
            Units are specified by a string or compiled regular
            expression (e.g. 'km', 'm s-1', ``re.compile('^kilo')``,
            etc.) or a `Units` object (e.g. ``Units('km')``,
            ``Units('m s-1')``, etc.).
            
        exact: `bool`, optional
            If `False` then select field constructs whose units are
            equivalent to any of those given by *units*. For example,
            metres and are equivelent to kilometres. By default, field
            constructs whose units are exactly one of those given by
            *units* are selected. Note that the format of the units is
            not important, i.e. 'm' is exactly the same as 'metres'
            for this purpose.
    
    :Returns:
    
        `FieldList`
            The matching field constructs.
    
    **Examples:**
    
    >>> gl = fl.filter_by_units('metres')
    >>> gl = fl.filter_by_units('m')
    >>> gl = fl.filter_by_units('m', 'kilogram')
    >>> gl = fl.filter_by_units(Units('m'))
    >>> gl = fl.filter_by_units('km', exact=False)
    >>> gl = fl.filter_by_units(Units('km'), exact=False)
    >>> gl = fl.filter_by_units(re.compile('^met'))
    >>> gl = fl.filter_by_units(Units('km'))
    >>> gl = fl.filter_by_units(Units('kg m-2'))

        '''
        return type(self)(f for f in self
                          if f.match_by_units(*units, exact=exact))


    # ----------------------------------------------------------------
    # Aliases
    # ----------------------------------------------------------------
    def filter(self, *identities):
        '''Alias for `cf.FieldList.filter_by_identity`.

        '''
        return self.filter_by_identity(*identities)
    

    def select(self, *identities, **kwargs):
        '''Alias of `cf.FieldList.filter_by_identity`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'select', kwargs,
                "Use methods 'filter_by_units',  'filter_by_construct', 'filter_by_properties', 'filter_by_naxes', 'filter_by_rank' instead.") # pragma: no cover

        if identities and isinstance(identities[0], (list, tuple, set)):
            _DEPRECATION_ERROR(
                "Use of a {!r} for identities has been deprecated. Use the * operator to unpack the arguments instead.".format(
                identities[0].__class__.__name__)) # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT(
                    "Use methods 'filter_by_units', 'filter_by_construct', 'filter_by_properties', 'filter_by_naxes', 'filter_by_rank' instead.") # pragma: no cover
            try:
                if ':' in i:
                    new = i.replace(':', '=', 1)
                    _DEPRECATION_ERROR(
                        "The ':' format has been deprecated. Use {!r} instead.".format(new)) # pragma: no cover
            except TypeError:
                pass
        #--- End: for
        
        return self.filter_by_identity(*identities)

    
    # ----------------------------------------------------------------
    # Deprecated attributes and methods
    # ----------------------------------------------------------------
    def _parameters(self, d):
        '''Deprecated at version 3.0.0.

        '''
        _DEPRECATION_ERROR_METHOD(self, '_parameters') # pragma: no cover


    def _deprecated_method(self, name):
        '''Deprecated at version 3.0.0.

        '''
        _DEPRECATION_ERROR_METHOD(self, '_deprecated_method') # pragma: no cover


    def set_equals(self, other, rtol=None, atol=None,
                   ignore_data_type=False, ignore_fill_value=False,
                   ignore_properties=(), ignore_compression=False,
                   ignore_type=False, traceback=False):
        '''Deprecated at version 3.0.0. Use method 'equals' instead.
        
        '''
        _DEPRECATION_ERROR_METHOD(self, 'set_equals',
                                  "Use method 'equals' instead.") # pragma: no cover


    def select_field(self, *args, **kwargs):
        '''Deprecated at version 3.0.0. Use 'fl.filter_by_*' methods instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'select_field',
                                  "Use 'fl.filter_by_*' methods instead.") # pragma: no cover


    def select1(self, *args, **kwargs):
        '''Deprecated at version 3.0.0. Use 'fl.filter_by_*' methods instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'select1', 
                                  "Use 'fl.filter_by_*' methods instead.") # pragma: no cover


#--- End: class