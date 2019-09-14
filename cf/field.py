from collections import OrderedDict
from copy        import deepcopy
from functools   import reduce
from operator    import mul as operator_mul
from operator    import itemgetter
import warnings

try:
    from scipy.ndimage.filters import convolve1d
    from scipy.signal          import get_window
    from matplotlib.path       import Path
except ImportError:
    pass

from numpy import arange      as numpy_arange
from numpy import argmax      as numpy_argmax
from numpy import array       as numpy_array
from numpy import array_equal as numpy_array_equal
from numpy import asanyarray  as numpy_asanyarray
from numpy import can_cast    as numpy_can_cast
from numpy import diff        as numpy_diff
from numpy import empty       as numpy_empty
from numpy import errstate    as numpy_errstate
from numpy import finfo       as numpy_finfo
from numpy import isnan       as numpy_isnan
from numpy import nan         as numpy_nan
from numpy import ndarray     as numpy_ndarray
from numpy import size        as numpy_size
from numpy import squeeze     as numpy_squeeze
from numpy import tile        as numpy_tile
from numpy import unique      as numpy_unique
from numpy import where       as numpy_where
from numpy import zeros       as numpy_zeros

from numpy.ma import is_masked   as numpy_ma_is_masked
from numpy.ma import isMA        as numpy_ma_isMA
from numpy.ma import MaskedArray as numpy_ma_MaskedArray
from numpy.ma import where       as numpy_ma_where
from numpy.ma import masked_invalid as numpy_ma_masked_invalid

import cfdm

from . import Bounds
from . import CellMethod
from . import DimensionCoordinate
from . import Domain
from . import DomainAxis
from . import Flags
from . import Constructs
from . import FieldList

from .constants import masked as cf_masked

from .functions import (parse_indices, CHUNKSIZE, equals,
                        RELAXED_IDENTITIES, IGNORE_IDENTITIES,
                        _section)
from .functions       import inspect as cf_inspect
from .query           import Query, ge, gt, le, lt, ne, eq, wi
from .regrid          import Regrid
from .timeduration    import TimeDuration
from .units           import Units

from .functions import (_DEPRECATION_ERROR,
                        _DEPRECATION_ERROR_KWARGS,
                        _DEPRECATION_ERROR_METHOD,
                        _DEPRECATION_ERROR_ATTRIBUTE,
                        _DEPRECATION_ERROR_DICT,
                        _DEPRECATION_ERROR_SEQUENCE)

from .data.data import Data

from . import mixin

_debug = False

# --------------------------------------------------------------------
# Commonly used units
# --------------------------------------------------------------------
_units_radians = Units('radians')
_units_metres  = Units('m')

# --------------------------------------------------------------------
# Map each allowed input collapse method name to its corresponding
# Data method. Input collapse methods not in this sictionary are
# assumed to have a corresponding Data method with the same name.
# --------------------------------------------------------------------
_collapse_methods = {
    'mean'              : 'mean',
    'avg'               : 'mean',
    'average'           : 'mean',
    'max'               : 'max',
    'maximum'           : 'max',
    'min'               : 'min',
    'minimum'           : 'min',
    'mid_range'         : 'mid_range',
    'range'             : 'range',
    'standard_deviation': 'sd',
    'sd'                : 'sd',
    'sum'               : 'sum',
    'variance'          : 'var',
    'var'               : 'var',
    'sample_size'       : 'sample_size', 
    'sum_of_weights'    : 'sum_of_weights',
    'sum_of_weights2'   : 'sum_of_weights2',
}

# --------------------------------------------------------------------
# Map each allowed input collapse method name to its corresponding
# Data method. Input collapse methods not in this sictionary are
# assumed to have a corresponding Data method with the same name.
# --------------------------------------------------------------------
_collapse_cell_methods = {
    'point'             : 'point',
    'mean'              : 'mean',
    'avg'               : 'mean',
    'average'           : 'mean',
    'max'               : 'maximum',
    'maximum'           : 'maximum',
    'min'               : 'minimum',
    'minimum'           : 'minimum',
    'mid_range'         : 'mid_range',
    'range'             : 'range',
    'standard_deviation': 'standard_deviation',
    'sd'                : 'standard_deviation',
    'sum'               : 'sum',
    'variance'          : 'variance',
    'var'               : 'variance',
    'sample_size'       : None,
    'sum_of_weights'    : None,
    'sum_of_weights2'   : None,
}

# --------------------------------------------------------------------
# Map each Data method to its corresponding minimum number of
# elements. Data methods not in this dictionary are assumed to have a
# minimum number of elements equal to 1.
# --------------------------------------------------------------------
_collapse_min_size = {'sd' : 2,
                      'var': 2,
                      }

# --------------------------------------------------------------------
# These Data methods may be weighted
# --------------------------------------------------------------------
_collapse_weighted_methods = set(('mean',
                                  'avg',
                                  'average',
                                  'sd',
                                  'standard_deviation',
                                  'var',
                                  'variance',
                                  'sum_of_weights',
                                  'sum_of_weights2',
                                  ))

# --------------------------------------------------------------------
# These Data methods may specify a number of degrees of freedom
# --------------------------------------------------------------------
_collapse_ddof_methods = set(('sd',
                              'var',
                              ))

#class DeprecationError(Exception):
 ##   '''Exception for removed methods'''
#    pass

# ====================================================================
#
# Field object
#
# ====================================================================

class Field(mixin.PropertiesData,
            cfdm.Field):
    '''A field construct of the CF data model.

The field construct is central to the CF data model, and includes all
the other constructs. A field corresponds to a CF-netCDF data variable
with all of its metadata. All CF-netCDF elements are mapped to a field
construct or some element of the CF field construct. The field
construct contains all the data and metadata which can be extracted
from the file using the CF conventions.

The field construct consists of a data array and the definition of its
domain (that describes the locations of each cell of the data array),
field ancillary constructs containing metadata defined over the same
domain, and cell method constructs to describe how the cell values
represent the variation of the physical quantity within the cells of
the domain. The domain is defined collectively by the following
constructs of the CF data model: domain axis, dimension coordinate,
auxiliary coordinate, cell measure, coordinate reference and domain
ancillary constructs.

The field construct also has optional properties to describe aspects
of the data that are independent of the domain. These correspond to
some netCDF attributes of variables (e.g. units, long_name and
standard_name), and some netCDF global file attributes (e.g. history
and institution).

**NetCDF interface**

The netCDF variable name of the construct may be accessed with the
`nc_set_variable`, `nc_get_variable`, `nc_del_variable` and
`nc_has_variable` methods.

    '''
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance._Constructs = Constructs
        instance._Domain     = Domain
        instance._DomainAxis = DomainAxis
        return instance


    _special_properties = mixin.PropertiesData._special_properties
    _special_properties += ('flag_values',
                            'flag_masks',
                            'flag_meanings')
        
    def __init__(self, properties=None, source=None, auto_cyclic=True,
                 copy=True, _use_data=True):
        '''**Initialization**

:Parameters:

    properties: `dict`, optional
        Set descriptive properties. The dictionary keys are
        property names, with corresponding values. Ignored if the
        *source* parameter is set.

        *Parameter example:*
          ``properties={'standard_name': 'air_temperature'}``
        
        Properties may also be set after initialisation with the
        `set_properties` and `set_property` methods.

    source: optional
        Initialize the properties, data and metadata constructs
        from those of *source*.
        
    autocyclic: `bool`, optional
        If `False` then do not auto-detect cyclic axes. By default
        cyclic axes are auto-detected with the `autocyclic`
        method.

    copy: `bool`, optional
        If `False` then do not deep copy input parameters prior to
        initialization. By default arguments are deep copied.

        '''
        super().__init__(properties=properties, source=source,
                         copy=copy, _use_data=_use_data)
        
        # Cyclic axes
        if auto_cyclic and source is None:
            self.autocyclic()


    def __getitem__(self, indices):
        '''f.__getitem__(indices) <==> f[indices]

    Return a subspace of the field defined by index values
    
    Subspacing by axis indices uses an extended Python slicing syntax,
    which is similar to :ref:`numpy array indexing
    <numpy:arrays.indexing>`. There are extensions to the numpy
    indexing functionality:
    
    * Size 1 axes are never removed.
    
      An integer index *i* takes the *i*-th element but does not
      reduce the rank of the output array by one:
    
      >>> f.shape
      (12, 73, 96)
      >>> f[0].shape
      (1, 73, 96)
      >>> f[3, slice(10, 0, -2), 95:93:-1].shape
      (1, 5, 2)
    
    * When more than one axis's slice is a 1-d boolean sequence or 1-d
      sequence of integers, then these indices work independently
      along each axis (similar to the way vector subscripts work in
      Fortran), rather than by their elements:
    
      >>> f.shape
      (12, 73, 96)
      >>> f[:, [0, 72], [5, 4, 3]].shape
      (12, 2, 3)
    
      Note that the indices of the last example would raise an error
      when given to a numpy array.
    
    * Boolean indices may be any object which exposes the numpy array
      interface, such as the field's coordinate objects:
    
      >>> f[:, f.coord('latitude')<0].shape
      (12, 36, 96)
    
    .. seealso `subspace`
    
    >>> f.shape
    (12, 73, 96)
    >>> f[...].shape
    (12, 73, 96)
    >>> f[slice(0, 12), :, 10:0:-2].shape
    (12, 73, 5)
    >>> f[..., f.coord('longitude')<180].shape
    (12, 73, 48)
    
    .. versionadded:: 2.0
    
    :Returns:
    
        `Field`
            The subspaced field construct.
    
    **Examples:**
    
    >>> g = f[..., 0, :6, 9:1:-2, [1, 3, 4]]

        '''
        if _debug:
            print(self.__class__.__name__+'.__getitem__') # pragma: no cover
            print('    input indices =', indices) # pragma: no cover
            
        if indices is Ellipsis:
            return self.copy()

        data  = self.data
        shape = data.shape

        # Parse the index
        if not isinstance(indices, tuple):
            indices = (indices,)

        if isinstance(indices[0], str) and indices[0] == 'mask':
            auxiliary_mask = indices[:2]
            indices2       = indices[2:]
        else:
            auxiliary_mask = None
            indices2       = indices

        indices, roll = parse_indices(shape, indices2, cyclic=True)

        if roll:
            new = self
            axes = data._axes
            cyclic_axes = data._cyclic
            for iaxis, shift in roll.items():
                axis = axes[iaxis]
                if axis not in cyclic_axes:
                    _ = self.get_data_axes()[iaxis]
                    raise IndexError(
                        "Can't take a cyclic slice from non-cyclic {!r} axis".format(
                            self.constructs.domain_axis_identity(_)))

                if _debug:
                    print('    roll, iaxis, shift =',  roll. iaxis, shift) # pragma: no cover

                new = new.roll(iaxis, shift)
        else:            
            new = self.copy()

        # ------------------------------------------------------------
        # Subspace the field's data
        # ------------------------------------------------------------
        if auxiliary_mask:
            auxiliary_mask = list(auxiliary_mask)
            findices = auxiliary_mask + indices
        else:
            findices = indices

        if _debug:
            print('    shape    =', shape) # pragma: no cover
            print('    indices  =', indices) # pragma: no cover
            print('    indices2 =', indices2) # pragma: no cover
            print('    findices =', findices) # pragma: no cover

                        
        new_data = new.data[tuple(findices)]

        # Set sizes of domain axes
        data_axes = new.get_data_axes()
        domain_axes = new.domain_axes
        for axis, size in zip(data_axes, new_data.shape):
            domain_axes[axis].set_size(size)
            
#        if roll:
#            new.set_data(new.data[tuple(findices)], copy=False)
#        else:
#            new.set_data(self.data[tuple(findices)], copy=False)

        # ------------------------------------------------------------
        # Subspace constructs with data
        # ------------------------------------------------------------
        if data_axes:
            construct_data_axes = new.constructs.data_axes()
    
            for key, construct in new.constructs.filter_by_axis('or', *data_axes).items():
                construct_axes = construct_data_axes[key]
                dice = []
                needs_slicing = False
                for axis in construct_axes:
                    if axis in data_axes:
                        needs_slicing = True
                        dice.append(indices[data_axes.index(axis)])
                    else:
                        dice.append(slice(None))
                #--- End: for
    
                # Generally we do not apply an auxiliary mask to the
                # metadata items, but for DSGs we do.
                if auxiliary_mask and new.DSG:
                    item_mask = []
                    for mask in auxiliary_mask[1]:                    
                        iaxes = [data_axes.index(axis) for axis in construct_axes
                                 if axis in data_axes]
                        for i, (axis, size) in enumerate(zip(data_axes, mask.shape)):
                            if axis not in construct_axes:
                                if size > 1:
                                    iaxes = None
                                    break
    
                                mask = mask.squeeze(i)
                        #--- End: for
                        
                        if iaxes is None:
                            item_mask = None
                            break
                        else:
                            mask1 = mask.transpose(iaxes)
                            for i, axis in enumerate(construct_axes):
                                if axis not in data_axes:
                                    mask1.inset_dimension(i)
                            #--- End: for
                            
                            item_mask.append(mask1)
                    #--- End: for
                    
                    if item_mask:
                        needs_slicing = True
                        dice = [auxiliary_mask[0], item_mask] + dice
                #--- End: if
                
                if _debug:
                    print('    dice = ', dice) # pragma: no cover
                    
                # Replace existing construct with its subspace
                if needs_slicing:
                    new.set_construct(construct[tuple(dice)], key=key,
                                      axes=construct_axes, copy=False)
            #--- End: for
        #--- End: if

        new.set_data(new_data, axes=data_axes, copy=False)
        
        return new


    def __repr__(self):
        '''Called by the `repr` built-in function.

    x.__repr__() <==> repr(x)

        '''
        return super().__repr__().replace('<', '<CF ', 1)


    def __setitem__(self, indices, value):
        '''Called to implement assignment to x[indices]=value

    x.__setitem__(indices, value) <==> x[indices]=value

    .. versionadded:: 2.0

        '''
        if isinstance(value, self.__class__):
            value = self._conform_for_assignment(value)
#        elif numpy_size(value) != 1:
#            raise ValueError(
#                "Can't assign a size {} {!r} to a {} data array".format(
#                    numpy_size(value), value.__class__.__name__,
#                    self.__class__.__name__))

        try:
            data = value.get_data(None)
        except AttributeError:
            pass
        else:
            if data is None:
                raise ValueError("Can't assign a {!r} with no data to a {}".format(
                    value.__class__.__name__, self.__class__.__name__))

            value = data
        
        self.data[indices] = value


    # 0
    def analyse_items(self, relaxed_identities=None):
        '''
Analyse a domain.

:Returns:

    `dict`
        A description of the domain.

**Examples:**

>>> print(f)
Axes           : time(3) = [1979-05-01 12:00:00, ..., 1979-05-03 12:00:00] gregorian
               : air_pressure(5) = [850.000061035, ..., 50.0000038147] hPa
               : grid_longitude(106) = [-20.5400109887, ..., 25.6599887609] degrees
               : grid_latitude(110) = [23.3200002313, ..., -24.6399995089] degrees
Aux coords     : latitude(grid_latitude(110), grid_longitude(106)) = [[67.1246607722, ..., 22.8886948065]] degrees_N
               : longitude(grid_latitude(110), grid_longitude(106)) = [[-45.98136251, ..., 35.2925499052]] degrees_E
Coord refs     : <CF CoordinateReference: rotated_latitude_longitude>

>>> f.analyse_items()
{
 'dim_coords': {'dim0': <CF Dim ....>,

 'aux_coords': {'N-d': {'aux0': <CF AuxiliaryCoordinate: latitude(110, 106) degrees_N>,
                        'aux1': <CF AuxiliaryCoordinate: longitude(110, 106) degrees_E>},
                'dim0': {'1-d': {},
                         'N-d': {}},
                'dim1': {'1-d': {},
                         'N-d': {}},
                'dim2': {'1-d': {},
                         'N-d': {'aux0': <CF AuxiliaryCoordinate: latitude(110, 106) degrees_N>,
                                 'aux1': <CF AuxiliaryCoordinate: longitude(110, 106) degrees_E>}},
                'dim3': {'1-d': {},
                         'N-d': {'aux0': <CF AuxiliaryCoordinate: latitude(110, 106) degrees_N>,
                                 'aux1': <CF AuxiliaryCoordinate: longitude(110, 106) degrees_E>}}},
 'axis_to_coord': {'dim0': <CF DimensionCoordinate: time(3) gregorian>,
                   'dim1': <CF DimensionCoordinate: air_pressure(5) hPa>,
                   'dim2': <CF DimensionCoordinate: grid_latitude(110) degrees>,
                   'dim3': <CF DimensionCoordinate: grid_longitude(106) degrees>},
 'axis_to_id': {'dim0': 'time',
                'dim1': 'air_pressure',
                'dim2': 'grid_latitude',
                'dim3': 'grid_longitude'},
 'cell_measures': {'N-d': {},
                   'dim0': {'1-d': {},
                            'N-d': {}},
                   'dim1': {'1-d': {},
                            'N-d': {}},
                   'dim2': {'1-d': {},
                            'N-d': {}},
                   'dim3': {'1-d': {},
                            'N-d': {}}},
 'id_to_aux': {},
 'id_to_axis': {'air_pressure': 'dim1',
                'grid_latitude': 'dim2',
                'grid_longitude': 'dim3',
                'time': 'dim0'},
 'id_to_coord': {'air_pressure': <CF DimensionCoordinate: air_pressure(5) hPa>,
                 'grid_latitude': <CF DimensionCoordinate: grid_latitude(110) degrees>,
                 'grid_longitude': <CF DimensionCoordinate: grid_longitude(106) degrees>,
                 'time': <CF DimensionCoordinate: time(3) gregorian>},
 'id_to_key': {'air_pressure': 'dim1',
               'grid_latitude': 'dim2',
               'grid_longitude': 'dim3',
               'time': 'dim0'},
 'undefined_axes': [],
 'warnings': [],
}

'''
        a = {}

        # ------------------------------------------------------------
        # Map each axis identity to its identifier, if such a mapping
        # exists.
        #
        # For example:
        # >>> id_to_axis
        # {'time': 'dim0', 'height': dim1'}
        # ------------------------------------------------------------
        id_to_axis = {}

        # ------------------------------------------------------------
        # For each dimension that is identified by a 1-d auxiliary
        # coordinate, map its dimension's its identifier.
        #
        # For example:
        # >>> id_to_aux
        # {'region': 'aux0'}
        # ------------------------------------------------------------
        id_to_aux = {}

        # ------------------------------------------------------------
        # The keys of the coordinate items which provide axis
        # identities
        #
        # For example:
        # >>> id_to_key
        # {'region': 'aux0'}
        # ------------------------------------------------------------
#        id_to_key = {}

        axis_to_id = {}

        # ------------------------------------------------------------
        # Map each dimension's identity to the coordinate which
        # provides that identity.
        #
        # For example:
        # >>> id_to_coord
        # {'time': <CF Coordinate: time(12)>}
        # ------------------------------------------------------------
        id_to_coord = {}

        axis_to_coord = {}

        # ------------------------------------------------------------
        # List the dimensions which are undefined, in that no unique
        # identity can be assigned to them.
        #
        # For example:
        # >>> undefined_axes
        # ['dim2']
        # ------------------------------------------------------------
        undefined_axes = []

        # ------------------------------------------------------------
        #
        # ------------------------------------------------------------
        warnings = []
        id_to_dim = {}
        axis_to_aux = {}
        axis_to_dim = {}

        if relaxed_identities is None:
            relaxed_identities = RELAXED_IDENTITIES()

        dimension_coordinates = self.dimension_coordinates

        for axis in self.domain_axes:
            
            dims = dimension_coordinates.filter_by_axis('and', axis)
            if len(dims) == 1:
                # This axis of the domain has a dimension coordinate
                key = dims.key()
                dim = dims.value()

                identity = None
                if relaxed_identities:
                    identities = dim.identities()
                    if identities:
                        identity = identities[0]
                else:
                    identity = dim.identity()

                if not identity:
                   # Dimension coordinate has no identity, but it may
                    # have a recognised axis.
                    for ctype in ('T', 'X', 'Y', 'Z'):
                        if getattr(dim, ctype):
                            identity = ctype
                            break
                #--- End: if

                if identity: # and dim.has_data():
                    if identity in id_to_axis:
                        warnings.append(
                            "Field has multiple {!r} axes".format(identity))

                    axis_to_id[axis]      = identity
                    id_to_axis[identity]  = axis
                    axis_to_coord[axis]   = key
                    id_to_coord[identity] = key
                    axis_to_dim[axis]     = key
                    id_to_dim[identity]   = key
                    continue

            else:
                auxs = self.auxiliary_coordinates.filter_by_axis('exact', axis)
                if len(auxs) == 1:                
                    # This axis of the domain does not have a
                    # dimension coordinate but it does have exactly
                    # one 1-d auxiliary coordinate, so that will do.
                    key, aux = dict(auxs).popitem()
                    
                    identity = None
                    if relaxed_identities:
                        identities = aux.identities()
                        if identities:
                            identity = identities[0]
                    else:
                        identity = aux.identity()
                    
                    if identity and aux.has_data():
                        if identity in id_to_axis:
                            warnings.append(
                                "Field has multiple {!r} axes".format(identity))

                        axis_to_id[axis]      = identity
                        id_to_axis[identity]  = axis
                        axis_to_coord[axis]   = key
                        id_to_coord[identity] = key
                        axis_to_aux[axis]     = key
                        id_to_aux[identity]   = key
                        continue
            #--- End: if

            # Still here? Then this axis is undefined
            undefined_axes.append(axis)
        #--- End: for

        return {
                'axis_to_id'    : axis_to_id,
                'id_to_axis'    : id_to_axis,
                'axis_to_coord' : axis_to_coord,
                'axis_to_dim'   : axis_to_dim,
                'axis_to_aux'   : axis_to_aux,
                'id_to_coord'   : id_to_coord,
                'id_to_dim'     : id_to_dim,
                'id_to_aux'     : id_to_aux,
                'undefined_axes': undefined_axes,
                'warnings'      : warnings,                
                }    
    #--- End def


    def _binary_operation(self, other, method):
        '''Implement binary arithmetic and comparison operations on the master
    data array with metadata-aware broadcasting.
    
    It is intended to be called by the binary arithmetic and
    comparison methods, such as `__sub__`, `__imul__`, `__rdiv__`,
    `__lt__`, etc.
    
    :Parameters:
    
        other: standard Python scalar object, `Field` or `Query` or `Data`
    
        method: `str`
            The binary arithmetic or comparison method name (such as
            ``'__idiv__'`` or ``'__ge__'``).
    
    :Returns:
    
        `Field`
            The new field, or the same field if the operation was an
            in place augmented arithmetic assignment.
    
    **Examples:**
    
    >>> h = f._binary_operation(g, '__add__')
    >>> h = f._binary_operation(g, '__ge__')
    >>> f._binary_operation(g, '__isub__')
    >>> f._binary_operation(g, '__rdiv__')

        '''
        _debug = False

#        if IGNORE_IDENTITIES():
#            inplace = method[2] == 'i'
#            data = self.data._binary_operation(other, method)
#            if self.shape != data.shape:
#                pass
#        
#            if inplace:
#                out = self
#            else:
#                out = self.copy()
#
#            out.set_data(data, axes=None, copy=False)
##  What?
#            return out
#
        if (isinstance(other, (float, int, bool, str)) or
            other is self):
            # ========================================================
            # CASE 1a: No changes to the field's items are required so
            #          can use the metadata-unaware parent method
            # ========================================================
            return super()._binary_operation(other, method)

        if isinstance(other, Data) and other.size == 1:
            # ========================================================
            # CASE 1b: No changes to the field's items are required
            #          so can use the metadata-unaware parent method
            # ========================================================
            if other.ndim > 0:
                other = other.squeeze()

            return super()._binary_operation(other, method)

        if isinstance(other, Query):
            # ========================================================
            # CASE 2: Combine the field with a Query object
            # ========================================================
            return NotImplemented

        if not isinstance(other, self.__class__):
            raise ValueError(
                "Can't combine {!r} with {!r}".format(
                    self.__class__.__name__, other.__class__.__name__))


        # ============================================================
        # Still here? Then combine the field with another field
        # ============================================================

        # ------------------------------------------------------------
        # Analyse each domain
        # ------------------------------------------------------------
        relaxed_identities = RELAXED_IDENTITIES()
        s = self.analyse_items(relaxed_identities=relaxed_identities)
        v = other.analyse_items(relaxed_identities=relaxed_identities)

        if _debug:
            print(s) # pragma: no cover
            print() # pragma: no cover
            print(v) # pragma: no cover
            print(v) # pragma: no cover
            print(self) # pragma: no cover
            print(other) # pragma: no cover
            
        if s['warnings'] or v['warnings']:
            raise ValueError(
                "Can't combine fields: {}".format(s['warnings'] or v['warnings']))
            
        # Check that at most one field has undefined axes
        if s['undefined_axes'] and v['undefined_axes']:
            raise ValueError(
                "Can't combine fields: Both fields have undefined axes: {!r}, {!r}".format(
                    tuple(self.constructs.domain_axis_identity(a) for a in s['undefined_axes']),
                    tuple(other.constructs.domain_axis_identity(a) for a in v['undefined_axes'])))
        
        # Find the axis names which are present in both fields
        matching_ids = set(s['id_to_axis']).intersection(v['id_to_axis'])
        if _debug:
            print("s['id_to_axis'] =", s['id_to_axis']) # pragma: no cover
            print("v['id_to_axis'] =", v['id_to_axis']) # pragma: no cover
            print('matching_ids    =', matching_ids) # pragma: no cover
        
        # Check that any matching axes defined by an auxiliary
        # coordinate are done so in both fields.
        for identity in set(s['id_to_aux']).symmetric_difference(v['id_to_aux']):
            if identity in matching_ids:
                raise ValueError(
"Can't combine fields: {!r} axis defined by auxiliary in only 1 field".format(
    standard_name)) ########~WRONG
        #--- End: for

        # ------------------------------------------------------------
        # For matching dimension coordinates check that they have
        # consistent coordinate references and that one of the following is
        # true:
        #
        # 1) They have equal size > 1 and their data arrays are
        #    equivalent
        #
        # 2) They have unequal sizes and one of them has size 1
        #
        # 3) They have equal size = 1. In this case, if the data
        #    arrays are not equivalent then the axis will be omitted
        #    from the result field.
        #-------------------------------------------------------------

        # List of size 1 axes to be completely removed from the result
        # field. Such an axis's size 1 defining coordinates have
        # unequivalent data arrays.
        #
        # For example:
        # >>> remove_size1_axes0
        # ['dim2']
        remove_size1_axes0 = []

        # List of matching axes with equivalent defining dimension
        # coordinate data arrays.
        #
        # Note that we don't need to include matching axes with
        # equivalent defining *auxiliary* coordinate data arrays.
        #
        # For example:
        # >>> 
        # [('dim2', 'dim0')]
        matching_axes_with_equivalent_data = {}

        # For each field, list those of its matching axes which need
        # to be broadcast against the other field. I.e. those axes
        # which are size 1 but size > 1 in the other field.
        #
        # For example:
        # >>> s['size1_broadcast_axes']
        # ['dim1']
        s['size1_broadcast_axes'] = []
        v['size1_broadcast_axes'] = []

#DO SOMETING WITH v['size1_broadcast_axes'] to be symmetrial with regards coord refs!!!!!
        
        # Map axes in field1 to axes in field0 and vice versa
        #
        # For example:
        # >>> axis1_to_axis0
        # {'dim1': 'dim0', 'dim2': 'dim1', 'dim0': 'dim2'}
        # >>> axis0_to_axis1
        # {'dim0': 'dim1', 'dim1': 'dim2', 'dim2': 'dim0'}
        axis1_to_axis0 = {}
        axis0_to_axis1 = {}

        remove_items = set()
        
        for identity in matching_ids:
            axis0  = s['id_to_axis'][identity]
            axis1  = v['id_to_axis'][identity]

            axis1_to_axis0[axis1] = axis0
            axis0_to_axis1[axis0] = axis1

            key0 = s['id_to_coord'][identity]
            key1 = v['id_to_coord'][identity]

            coord0 = self.constructs[key0]
            coord1 = other.constructs[key1]

            # Check the sizes of the defining coordinates
            size0 = coord0.size
            size1 = coord1.size
            if size0 != size1:
                # Defining coordinates have different sizes
                if size0 == 1:
                    # Broadcast
                    s['size1_broadcast_axes'].append(axis0)
                elif size1 == 1:
                    # Broadcast
                    v['size1_broadcast_axes'].append(axis1)
                else:
                    # Can't broadcast
                    raise ValueError(
"Can't combine fields: Can't broadcast {!r} axes with sizes {} and {}".format(
    identity, size0, size1))

                # Move on to the next identity if the defining
                # coordinates have different sizes
                continue

            # Still here? Then the defining coordinates have the same
            # size.

            # Check that equally sized defining coordinate data arrays
            # are compatible
            if coord0._equivalent_data(coord1, verbose=_debug):
                # The defining coordinates have equivalent data
                # arrays
            
                # If the defining coordinates are attached to
                # coordinate references then check that those
                # coordinate references are equivalent

                # For each field, find the coordinate references which
                # contain the defining coordinate.
#                refs0 = [ref for ref in self.coordinate_references.values()
#                         if key0 in ref.coordinates()]
                refs0 = [key for key, ref in self.coordinate_references.items()
                         if key0 in ref.coordinates()]
                refs1 = [key for key, ref in other.coordinate_references.items()
                         if key1 in ref.coordinates()]

                nrefs = len(refs0)
                if nrefs > 1 or nrefs != len(refs1):
                    # The defining coordinate are associated with
                    # different numbers of coordinate references
                    equivalent_refs = False
                elif not nrefs:
                    # Neither defining coordinate is associated with a
                    # coordinate reference                    
                    equivalent_refs = True
                else:  
                    # Each defining coordinate is associated with
                    # exactly one coordinate reference
                    equivalent_refs = self._equivalent_coordinate_references(
                        other, key0=refs0[0], key1=refs1[0], s=s, t=v,
                        verbose=_debug)

                if not equivalent_refs:
                    # The defining coordinates have non-equivalent
                    # coordinate references
                    if coord0.size == 1:
                        # The defining coordinates have non-equivalent
                        # coordinate references but both defining
                        # coordinates are of size 1 => flag this axis
                        # to be omitted from the result field.
#dch                        remove_size1_axes0.append(axis0)
                        key0 = refs0[0]
                        ref0 = self.coordinate_references[key0]
                        remove_items.add(refs0[0])
                        remove_items.update(ref0.coordinate_conversion.domain_ancillaries().values())
                    else:
                        # The defining coordinates have non-equivalent
                        # coordinate references and they are of size >
                        # 1
                        raise ValueError(
                            "Can't combine fields: Incompatible coordinate references for {!r} coordinates".format(
                                identity))

                elif identity not in s['id_to_aux']:
                    # The defining coordinates are both dimension
                    # coordinates, have equivalent data arrays and
                    # have equivalent coordinate references.
                    matching_axes_with_equivalent_data[axis0] = axis1
                else:
                    # The defining coordinates are both auxiliary
                    # coordinates, have equivalent data arrays and
                    # have equivalent coordinate references.
                    pass

            else:
                if coord0.size > 1:
                    # The defining coordinates have non-equivalent
                    # data arrays and are both of size > 1
                    raise ValueError(
"Can't combine fields: Incompatible {!r} coordinate values: {}, {}".format(
    identity, coord0.data, coord1.data))
                else:
                    # The defining coordinates have non-equivalent
                    # data arrays and are both size 1 => this axis to
                    # be omitted from the result field
                    remove_size1_axes0.append(axis0)
        #--- End: for
        if _debug:
            print("1: s['size1_broadcast_axes'] =", s['size1_broadcast_axes']) # pragma: no cover
            print("1: v['size1_broadcast_axes'] =", v['size1_broadcast_axes']) # pragma: no cover
            print('1: remove_size1_axes0 =', remove_size1_axes0) # pragma: no cover

        matching_axis1_to_axis0 = axis1_to_axis0.copy()
        matching_axis0_to_axis1 = axis0_to_axis1.copy()

        # ------------------------------------------------------------
        # Still here? Then the two fields are combinable!
        # ------------------------------------------------------------

        # ------------------------------------------------------------
        # 2.1 Create copies of the two fields, unless it is an in
        #     place combination, in which case we don't want to copy
        #     self)
        # ------------------------------------------------------------
        field1 = other.copy()

        inplace = method[2] == 'i'
        if not inplace:
            field0 = self.copy()
        else:
            field0 = self

        s['new_size1_axes'] = []
            
        # ------------------------------------------------------------
        # Permute the axes of the data array of field0 so that:
        #
        # * All of the matching axes are the inner (fastest varying)
        #   axes
        #
        # * All of the undefined axes are the outer (slowest varying)
        #   axes
        #
        # * All of the defined but unmatched axes are in the middle
        # ------------------------------------------------------------
        data_axes0 = field0.get_data_axes()
        axes_unD = []                     # Undefined axes
        axes_unM = []                     # Defined but unmatched axes
        axes0_M  = []                     # Defined and matched axes
        for axis0 in data_axes0:
            if axis0 in axis0_to_axis1:
                # Matching axis                
                axes0_M.append(axis0)
            elif axis0 in s['undefined_axes']:
                # Undefined axis
                axes_unD.append(axis0)
            else:
                # Defined but unmatched axis
                axes_unM.append(axis0)
        #--- End: for
        if _debug:
            print('2: axes_unD, axes_unM , axes0_M =', axes_unD , axes_unM , axes0_M) # pragma: no cover

        field0.transpose(axes_unD + axes_unM + axes0_M, inplace=True)

        end_of_undefined0   = len(axes_unD)
        start_of_unmatched0 = end_of_undefined0
        start_of_matched0   = start_of_unmatched0 + len(axes_unM)
        if _debug: 
            print('2: end_of_undefined0   =', end_of_undefined0   ) # pragma: no cover
            print('2: start_of_unmatched0 =', start_of_unmatched0 ) # pragma: no cover
            print('2: start_of_matched0   =', start_of_matched0  ) # pragma: no cover

        # ------------------------------------------------------------
        # Permute the axes of the data array of field1 so that:
        #
        # * All of the matching axes are the inner (fastest varying)
        #   axes and in corresponding positions to data0
        #
        # * All of the undefined axes are the outer (slowest varying)
        #   axes
        #
        # * All of the defined but unmatched axes are in the middle
        # ------------------------------------------------------------
        data_axes1 = field1.get_data_axes()
        axes_unD = []
        axes_unM = []
        axes1_M  = [axis0_to_axis1[axis0] for axis0 in axes0_M]
        for  axis1 in data_axes1:          
            if axis1 in axes1_M:
                pass
            elif axis1 in axis1_to_axis0:
                # Matching axis
                axes_unM.append(axis1)
            elif axis1 in v['undefined_axes']:
                # Undefined axis
                axes_unD.append(axis1) 
            else:
                # Defined but unmatched axis
                axes_unM.append(axis1)
        #--- End: for
        if _debug:
            print('2: axes_unD , axes_unM , axes0_M =',axes_unD , axes_unM , axes0_M) # pragma: no cover

        field1.transpose(axes_unD + axes_unM + axes1_M, inplace=True)

        start_of_unmatched1 = len(axes_unD)
        start_of_matched1   = start_of_unmatched1 + len(axes_unM)
        undefined_indices1  = slice(None, start_of_unmatched1)
        unmatched_indices1  = slice(start_of_unmatched1, start_of_matched1)
        if _debug: 
            print('2: start_of_unmatched1 =', start_of_unmatched1 ) # pragma: no cover
            print('2: start_of_matched1   =', start_of_matched1   ) # pragma: no cover
            print('2: undefined_indices1  =', undefined_indices1  ) # pragma: no cover
            print('2: unmatched_indices1  =', unmatched_indices1  ) # pragma: no cover

        # ------------------------------------------------------------
        # Make sure that each pair of matching axes run in the same
        # direction 
        #
        # Note that the axis0_to_axis1 dictionary currently only maps
        # matching axes
        # ------------------------------------------------------------
        if _debug:
            print('2: axis0_to_axis1 =',axis0_to_axis1) # pragma: no cover

        for axis0, axis1 in axis0_to_axis1.items():
            if field1.direction(axis1) != field0.direction(axis0):
                field1.flip(axis1, inplace=True)
        #--- End: for
    
        # ------------------------------------------------------------
        # 2f. Insert size 1 axes into the data array of field0 to
        #     correspond to defined but unmatched axes in field1
        #
        # For example, if   field0.data is      1 3         T Y X
        #              and  field1.data is          4 1 P Z   Y X
        #              then field0.data becomes 1 3     1 1 T Y X
        # ------------------------------------------------------------
        unmatched_axes1 = data_axes1[unmatched_indices1]
        if _debug: 
            print('2: unmatched_axes1=', unmatched_axes1) # pragma: no cover

        if unmatched_axes1:
            for axis1 in unmatched_axes1:
                new_axis = field0.set_construct(field0._DomainAxis(1))
                field0.insert_dimension(new_axis, end_of_undefined0, inplace=True)
                if _debug: 
                    print('2: axis1, field0.shape =', axis1, field0.data.shape) # pragma: no cover
                
                axis0 = set(field0.get_data_axes()).difference(data_axes0).pop()

                axis1_to_axis0[axis1] = axis0
                axis0_to_axis1[axis0] = axis1
                s['new_size1_axes'].append(axis0)

                start_of_unmatched0 += 1
                start_of_matched0   += 1 

                data_axes0 = field0.get_data_axes()
        #--- End: if

        # ------------------------------------------------------------
        # Insert size 1 axes into the data array of field1 to
        # correspond to defined but unmatched axes in field0
        #
        # For example, if   field0.data is      1 3     1 1 T Y X
        #              and  field1.data is          4 1 P Z   Y X 
        #              then field1.data becomes     4 1 P Z 1 Y X 
        # ------------------------------------------------------------
        unmatched_axes0 = data_axes0[start_of_unmatched0:start_of_matched0]
        if _debug:
            print('2: unmatched_axes0 =', unmatched_axes0) # pragma: no cover

        if unmatched_axes0:
            for axis0 in unmatched_axes0:
                new_axis = field1.set_construct(field1._DomainAxis(1))
                field1.insert_dimension(new_axis, start_of_matched1, inplace=True)
                if _debug:
                    print('2: axis0, field1.shape =',axis0, field1.shape) # pragma: no cover

                axis1 = set(field1.get_data_axes()).difference(data_axes1).pop()

                axis0_to_axis1[axis0] = axis1
                axis1_to_axis0[axis1] = axis0

                start_of_unmatched1 += 1

                data_axes1 = field1.get_data_axes()
         #--- End: if

        # ------------------------------------------------------------
        # Insert size 1 axes into the data array of field0 to
        # correspond to undefined axes (of any size) in field1
        #
        # For example, if   field0.data is      1 3     1 1 T Y X
        #              and  field1.data is          4 1 P Z 1 Y X 
        #              then field0.data becomes 1 3 1 1 1 1 T Y X
        # ------------------------------------------------------------
        axes1 = data_axes1[undefined_indices1]
        if axes1:
            for axis1 in axes1:
                new_axis = field0.set_construct(field0._DomainAxis(1))
                field0.insert_dimension(new_axis, end_of_undefined0, inplace=True)

                axis0 = set(field0.get_data_axes()).difference(data_axes0).pop()

                axis0_to_axis1[axis0] = axis1
                axis1_to_axis0[axis1] = axis0
                s['new_size1_axes'].append(axis0)

                data_axes0 = field0.get_data_axes()
        #--- End: if
        if _debug:
            print('2: axis0_to_axis1 =', axis0_to_axis1) # pragma: no cover
            print('2: axis1_to_axis0 =', axis1_to_axis0) # pragma: no cover
            print("2: s['new_size1_axes']  =", s['new_size1_axes']) # pragma: no cover

        # ============================================================
        # 3. Combine the data objects
        #
        # Note that, by now, field0.ndim >= field1.ndim.
        # ============================================================
#dch        field0.Data = getattr(field0.Data, method)(field1.Data)
        if _debug:
            print() # pragma: no cover
            print('3: repr(field0) =', repr(field0)) # pragma: no cover
            print('3: repr(field1) =', repr(field1)) # pragma: no cover

        new_data0 = field0.data._binary_operation(field1.data, method)
        
#        field0 = super(Field, field0)._binary_operation(field1, method)

        if _debug:
            print('3: field0.shape =', field0.shape) # pragma: no cover
            print('3: repr(field0) =', repr(field0)) # pragma: no cover

        # ============================================================
        # 4. Adjust the domain of field0 to accommodate its new data
        # ============================================================
        # Field 1 dimension coordinate to be inserted into field 0
        insert_dim        = {}
        # Field 1 auxiliary coordinate to be inserted into field 0
        insert_aux        = {}
        # Field 1 domain ancillaries to be inserted into field 0
        insert_domain_anc = {}
        # Field 1 coordinate references to be inserted into field 0
        insert_ref   = set()

        # ------------------------------------------------------------
        # 4a. Remove selected size 1 axes
        # ------------------------------------------------------------
        if _debug:
            print('4: field0.constructs.keys() =', sorted(field0.constructs.keys())) # pragma: no cover
            print('4: field1.constructs.keys() =', sorted(field1.constructs.keys())) # pragma: no cover

        #AND HEREIN LIES THE PROBLEM            TODO
        for size1_axis in remove_size1_axes0:
#            field0.remove_axis(size1_axis)
            field0.del_construct(size1_axis)

        # ------------------------------------------------------------
        # 4b. If broadcasting has grown any size 1 axes in field0
        #     then replace their size 1 coordinates with the
        #     corresponding size > 1 coordinates from field1.
        # ------------------------------------------------------------
        refs0 = dict(field0.coordinate_references)
        refs1 = dict(field1.coordinate_references)

        for axis0 in s['size1_broadcast_axes'] + s['new_size1_axes']:
            axis1 = axis0_to_axis1[axis0]
#            field0._Axes[axis0] = field1._Axes[axis1]
            field0.set_construct(field1.domain_axes[axis1], key=axis0)
            if _debug:
                print('4: field0 domain axes =',field0.domain_axes) # pragma: no cover
                print('4: field1 domain axes =',field1.domain_axes) # pragma: no cover

            # Copy field1 1-d coordinates for this axis to field0
#            if axis1 in field1.Items.d:
            if axis1 in field1.dimension_coordinates:
                insert_dim[axis1] = [axis0]

#            for key1 in field1.Items(role='a', axes_all=set((axis1,))):
            for key1 in field1.auxiliary_coordinates.filter_by_axis('exact', axis1):
                insert_aux[key1] = [axis0]

            # Copy field1 coordinate references which span this axis
            # to field0, along with all of their domain ancillaries
            # (even if those domain ancillaries do not span this
            # axis).
            for key1, ref1 in refs1.items():
                if axis1 not in field1.coordinate_reference_domain_axes(key1):
                    continue
#                insert_ref.add(key1)
#                for identifier1 in ref1.ancillaries.values():
#                    key1 = field1.key(identifier1, exact=True, role='c')
#                    if key1 is not None:
#                        axes0 = [axis1_to_axis0[axis]ct2', 'dim1', 'dim2', 'fav0', 'fav1', 'fav2', 'fav3', 'msr0', 'ref1']
#5: field1.Items().keys() = ['aux0', 'aux1', 'aux2', 'c
#                                 for axis in field1.Items.axes(key1)]
#                        insert_domain_anc[key1] = axes0
            #--- End: for

            # Remove all field0 auxiliary coordinates and domain
            # ancillaries which span this axis
#            remove_items.update(field0.Items(role='ac', axes=set((axis0,))))
            c = field0.constructs.filter_by_type('auxiliary_coordinate', 'domain_ancillary')
            remove_items.update(c.filter_by_axis('and', axis0))

            # Remove all field0 coordinate references which span this
            # axis, and their domain ancillaries (even if those domain
            # ancillaries do not span this axis).
            for key0 in tuple(refs0):
                if axis0 in field0.coordinate_reference_domain_axes(key0):
                    ref0 = refs0.pop(key0)
                    remove_items.add(key0)
                    remove_items.update(field0.domain_ancillaries(
                        *tuple(ref0.coordinate_conversion.domain_ancillaries().values())))
#                    remove_items.update(field0.Items(ref0.ancillaries.values(), 
#                                                     exact=True, role='c'))
            #--- End: for
        #--- End: for

        # ------------------------------------------------------------
        # Consolidate auxiliary coordinates for matching axes
        #
        # A field0 auxiliary coordinate is retained if:
        #
        # 1) it is the defining coordinate for its axis
        #
        # 2) there is a corresponding field1 auxiliary coordinate
        #    spanning the same axes which has the same identity and
        #    equivalent data array
        #
        # 3) there is a corresponding field1 auxiliary coordinate
        #    spanning the same axes which has the same identity and a
        #    size-1 data array.
        #-------------------------------------------------------------
        auxs1 = dict(field1.auxiliary_coordinates)
        if _debug:
            print('5: field0.auxs() =', field0.auxiliary_coordinates) # pragma: no cover
            print('5: field1.auxs() =', auxs1) # pragma: no cover
            print('5: remove_items =', remove_items) # pragma: no cover

        for key0, aux0 in field0.auxiliary_coordinates.items():
            if key0 in remove_items:
                # Field0 auxiliary coordinate has already marked for
                # removal
                continue
            
            if key0 in s['id_to_aux'].values():
                # Field0 auxiliary coordinate has already been checked
                continue
            
            if aux0.identity() is None:
                # Auxiliary coordinate has no identity
                remove_items.add(key0)
                continue        

            axes0 = field0.get_data_axes(key0)
            if not set(axes0).issubset(matching_axis0_to_axis1):
                # Auxiliary coordinate spans at least on non-matching
                # axis
                remove_items.add(key0)
                continue
                
            found_equivalent_auxiliary_coordinates = False
            for key1, aux1 in auxs1.copy().items():
                if key1 in v['id_to_aux'].values():
                    # Field1 auxiliary coordinate has already been checked
                    del auxs1[key1]
                    continue            

                if aux1.identity() is None:
                    # Field1 auxiliary coordinate has no identity
                    del auxs1[key1]
                    continue        

                axes1 = field1.get_data_axes(key0)
                if not set(axes1).issubset(matching_axis1_to_axis0):
                    # Field 1 auxiliary coordinate spans at least one
                    # non-matching axis
                    del auxs1[key1]
                    continue

                if field1.constructs[key1].size == 1:
                    # Field1 auxiliary coordinate has size-1 data array
                    found_equivalent_auxiliary_coordinates = True
                    del auxs1[key1]
                    break

                if field0._equivalent_construct_data(field1,
                                                     key0=key0, key1=key1, s=s, t=v):
                    # Field0 auxiliary coordinate has equivalent data
                    # to a field1 auxiliary coordinate
                    found_equivalent_auxiliary_coordinates = True
                    del auxs1[key1]
                    break
            #--- End: for                

            if not found_equivalent_auxiliary_coordinates:
                remove_items.add(key0)
        #--- End: for

        # ------------------------------------------------------------
        # Copy field1 auxiliary coordinates which do not span any
        # matching axes to field0
        # ------------------------------------------------------------
        for key1 in field1.auxiliary_coordinates:
            if key1 in insert_aux:
                continue
            
            axes1 = field1.constructs.data_axes()[key1]
            if set(axes1).isdisjoint(matching_axis1_to_axis0):
                insert_aux[key1] = [axis1_to_axis0[axis1] for axis1 in axes1]
        #--- End: for

        # ------------------------------------------------------------
        # Insert field1 items into field0
        # ------------------------------------------------------------

        # Map field1 items keys to field0 item keys
        key1_to_key0 = {}

        if _debug:
            print('5: insert_dim               =', insert_dim                      ) # pragma: no cover
            print('5: insert_aux               =', insert_aux                      ) # pragma: no cover
            print('5: insert_domain_anc        =', insert_domain_anc               ) # pragma: no cover
            print('5: insert_ref               =', insert_ref                      ) # pragma: no cover
            print('5: field0.constructs.keys() =', sorted(field0.constructs.keys())) # pragma: no cover
            print('5: field1.constructs.keys() =', sorted(field1.constructs.keys())) # pragma: no cover

        for key1, axes0 in insert_dim.items():
            try:
#                key0 = field0.insert_dim(field1.Items[key1], axes=axes0)
                key0 = field0.set_construct(field1.dimension_coordinates[key1],
                                            axes=axes0)
            except ValueError:
                # There was some sort of problem with the insertion, so
                # just ignore this item.
                pass
            else:
                key1_to_key0[key1] = key0

            if _debug:
                print('axes0, key1, field1.constructs[key1] =',
                      axes0, key1, repr(field1.constructs[key1])) # pragma: no cover
                
        for key1, axes0 in insert_aux.items():
            try:
#                key0 = field0.insert_aux(field1.Items[key1], axes=axes0)
                key0 = field0.set_construct(field1.auxiliary_coordinates[key1],
                                            axes=axes0)
            except ValueError:
                # There was some sort of problem with the insertion, so
                # just ignore this item.
                pass
            else:
                key1_to_key0[key1] = key0
                
            if _debug:
                print('axes0, key1, field1.constructs[key1] =',
                      axes0, key1, repr(field1.constructs[key1])) # pragma: no cover
                
        for key1, axes0 in insert_domain_anc.items():
            try:
#                key0 = field0.insert_domain_anc(field1.constructs[key1], axes=axes0)
                key0 = field0.set_construct(field1.domain_ancillaries[key1], axes=axes0)
            except ValueError as error:
                # There was some sort of problem with the insertion, so
                # just ignore this item.
                if _debug:
                    print('Domain ancillary insertion problem:', error) # pragma: no cover
            else:
                key1_to_key0[key1] = key0

            if _debug:
                print('domain ancillary axes0, key1, field1.constructs[key1] =',
                      axes0, key1, repr(field1.constructs[key1])) # pragma: no cover

        # ------------------------------------------------------------
        # Remove field0 which are no longer required
        # ------------------------------------------------------------
        if remove_items:
            if _debug:
                print(sorted(field0.constructs.keys())) # pragma: no cover
                print('Removing {!r} from field0'.format(sorted(remove_items))) # pragma: no cover

#            field0.remove_items(remove_items, role='facdmr')
            for key in remove_items:
                field0.del_construct(key, default=None)

        # ------------------------------------------------------------
        # Copy coordinate references from field1 to field0 (do this
        # after removing any coordinates and domain ancillaries)
        # ------------------------------------------------------------
        for key1 in insert_ref:
            ref1 = field1.coordinate_references[key1]
            if _debug:
                print('Copying {!r} from field1 to field0'.format(ref1)) # pragma: no cover

            identity_map = dict(field1.constructs.filter_by_type('dimension_coordinate',
                                                                 'axuiliary_coordinate',
                                                                 'domain_ancillary'))
            for key1, item1 in identity_map.copy().items():
#                identity_map[key1] = key1_to_key0.get(key1, None)
                identity_map[key1] = key1_to_key0.get(key1, item1.identity())

            new_ref0 = ref1.change_identifiers(identity_map, strict=True)
            
#            field0.insert_ref(new_ref0, copy=False)
            field0.set_construct(new_ref0, copy=False)
        
        field0.set_data(new_data0, set_axes=False, copy=False)
        
        return field0


    def _conform_coordinate_references(self, key):
        '''Where possible, replace the content of ref.coordinates with
    coordinate construct keys and the values of domain ancillary terms
    with domain ancillary construct keys.

    :Parameters:
    
        key: `str`
            Coordinate construct key.
    
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> f._conform_coordinate_references('aucxiliarycoordinate1')

        '''
        identity = self.constructs[key].identity(strict=True)
        
        for ref in self.coordinate_references.values():
            if key in ref.coordinates():
                continue
            
            if identity in ref._coordinate_identities:
                ref.set_coordinate(key)


    def _conform_cell_methods(self):
        '''TODO

    :Parameters:
    
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> f._conform_cell_methods()

        '''
        axis_map = {}        

        for cm in self.cell_methods.values():
            for axis in cm.get_axes(()):
                if axis in axis_map:
                    continue
                
                if axis == 'area':
                    axis_map[axis] = axis
                    continue
                
                axis_map[axis] = self.domain_axis(axis, key=True, default=axis)
            #--- End: for

            cm.change_axes(axis_map, inplace=True)
        #--- End: for
        
    def _equivalent_coordinate_references(self, field1, key0, key1,
                                          atol=None, rtol=None,
                                          s=None, t=None,
                                          verbose=False):
        '''TODO

    Two real numbers ``x`` and ``y`` are considered equal if
    ``|x-y|<=atol+rtol|y|``, where ``atol`` (the tolerance on absolute
    differences) and ``rtol`` (the tolerance on relative differences)
    are positive, typically very small numbers. See the *atol* and
    *rtol* parameters.
    
    :Parameters:
     
        ref0: `CoordinateReference`
    
        ref1: `CoordinateReference`
    
        field1: `Field`
            The field which contains *ref1*.
    
    :Returns:
    
        `bool`

        '''
        ref0 = self.coordinate_references[key0]
        ref1 = field1.coordinate_references[key1]

        if not ref0.equivalent(ref1, rtol=rtol, atol=atol,
                               verbose=verbose):
            if verbose:
                print(
                    "{}: Non-equivalent coordinate references ({!r}, {!r})".format(
                        self.__class__.__name__, ref0, ref1)) # pragma: no cover
            return False

        # Compare the domain ancillaries
        for term, identifier0 in ref0.coordinate_conversion.domain_ancillaries().items():
            if identifier0 is None:
                continue

            identifier1 = ref1.coordinate_conversion.domain_ancillaries()[term]
            
            key0 = self.domain_ancillaries.filter_by_key(identifier0).key()            
            key1 = field1.domain_ancillaries.filter_by_key(identifier1).key()

            if not self._equivalent_construct_data(field1, key0=key0,
                                                   key1=key1, rtol=rtol,
                                                   atol=atol, s=s, t=t,
                                                   verbose=verbose):
                # add traceback TODO
                return False
        #--- End: for

        return True

    
    def _set_construct_parse_axes(self, item, axes=None, allow_scalar=True):
        '''TODO

    :Returns:

        `list`

        '''
        data = item.get_data(None)
        
        if axes is None:
            # --------------------------------------------------------
            # The axes have not been set => infer the axes.
            # --------------------------------------------------------
            if data is not None:
                shape = item.shape
                if allow_scalar and shape == ():
                    axes = []
                else:
                    if not allow_scalar and not shape:
                        shape = (1,)
                
                    if not shape or len(shape) != len(set(shape)):
                        raise ValueError(
                            "Can't insert {0}: Ambiguous shape: {1}. Consider setting the 'axes' parameter.".format(
                                item.__class__.__name__, shape))
                
                    axes = []
                    axes_sizes = [domain_axis.get_size(None)
                                  for domain_axis in self.domain_axes.values()]
                    for n in shape:
                        if axes_sizes.count(n) == 1:
                            axes.append(self.domain_axes.filter_by_size(n).key())
                        else:
                            raise ValueError(
                                "Can't insert {} {}: Ambiguous shape: {}. Consider setting the 'axes' parameter.".format(
                                    item.identity(), item.__class__.__name__, shape))
        else:
            # --------------------------------------------------------
            # Axes have been provided
            # --------------------------------------------------------
            if axes and data is not None:
                ndim = item.ndim
                if not ndim and not allow_scalar:
                    ndim = 1
    
                if len(axes) != ndim or len(set(axes)) != ndim:
                    raise ValueError(
                        "Can't insert {} {}: Incorrect number of given axes (got {}, expected {})".format(
                            item.identity(), item.__class__.__name__, len(set(axes)), ndim))
                
                axes2 = []
                for axis, size in zip(axes, item.data.shape):
                    dakey = self.domain_axis(axis, key=True, default=ValueError(
                        "Unknown axis: {!r}".format(axis)))
#                    dakey = self.domain_axis(axis, key=True, default=None)
#                    if axis is None:
#                        raise ValueError("Unknown axis: {!r}".format(axis))
                                         
                    axis_size = self.domain_axes[dakey].get_size(None)
                    if size != axis_size:
                        raise ValueError(
                            "Can't insert {} {}: Mismatched axis size ({} != {})".format(
                                item.identity(), item.__class__.__name__, size,
                                axis_size))
    
                    axes2.append(dakey)
                #--- End: for
                
                axes = axes2
    
                if ndim != len(set(axes)):
                    raise ValueError(
                        "Can't insert {} {}: Mismatched number of axes ({} != {})".format(
                            item.identity(), item.__class__.__name__, len(set(axes)), ndim))
        #--- End: if
    
        return axes


    def _conform_for_assignment(self, other):
        '''Conform *other* so that it is ready for metadata-unaware assignment
    broadcasting across *self*.

    Note that *other* is not changed.
    
    :Parameters:
    
        other: `Field`
            The field to conform.
    
    :Returns:
    
        `Field`
            The conformed version of *other*.
    
    **Examples:**
    
    >>> g = _conform_for_assignment(f)

        '''
        # Analyse each domain
        s = self.analyse_items()
        v = other.analyse_items()
    
        if s['warnings'] or v['warnings']:
            raise ValueError(
                "Can't setitem: {0}".format(s['warnings'] or v['warnings']))
    
        # Find the set of matching axes
        matching_ids = set(s['id_to_axis']).intersection(v['id_to_axis'])
        if not matching_ids:
            raise ValueError("Can't assign: No matching axes")
    
        # ------------------------------------------------------------
        # Check that any matching axes defined by auxiliary
        # coordinates are done so in both fields.
        # ------------------------------------------------------------
        for identity in matching_ids:
            if (identity in s['id_to_aux']) + (identity in v['id_to_aux']) == 1:
                raise ValueError(
                    "Can't assign: {0!r} axis defined by auxiliary in only 1 field".format(
                        identity))
        #--- End: for
    
        copied = False
    
        # ------------------------------------------------------------
        # Check that 1) all undefined axes in other have size 1 and 2)
        # that all of other's unmatched but defined axes have size 1
        # and squeeze any such axes out of its data array.
        #
        # For example, if   self.data is        P T     Z Y   X   A
        #              and  other.data is     1     B C   Y 1 X T
        #              then other.data becomes            Y   X T
        # ------------------------------------------------------------
        squeeze_axes1 = []
        for axis1 in v['undefined_axes']:
            axis_size = other.domain_axes[axis1].get_size()
            if axis_size != 1:            
                raise ValueError(
                    "Can't assign: Can't broadcast undefined axis with size {}".format(
                        axis_size))

            squeeze_axes1.append(axis1)

        for identity in set(v['id_to_axis']).difference(matching_ids):
            axis1 = v['id_to_axis'][identity]
            axis_size = other.domain_axes[axis1].get_size()
            if axis_size != 1:
               raise ValueError(
                   "Can't assign: Can't broadcast size {0} {1!r} axis".format(
                       axis_size, identity))
           
            squeeze_axes1.append(axis1)    

        if squeeze_axes1:
            if not copied:
                other = other.copy()
                copied = True

            other.squeeze(squeeze_axes1, inplace=True)

        # ------------------------------------------------------------
        # Permute the axes of other.data so that they are in the same
        # order as their matching counterparts in self.data
        #
        # For example, if   self.data is       P T Z Y X   A
        #              and  other.data is            Y X T
        #              then other.data becomes   T   Y X
        # ------------------------------------------------------------
        data_axes0 = self.get_data_axes()
        data_axes1 = other.get_data_axes()

        transpose_axes1 = []       
        for axis0 in data_axes0:
            identity = s['axis_to_id'][axis0]
            if identity in matching_ids:
                axis1 = v['id_to_axis'][identity]                
                if axis1 in data_axes1:
                    transpose_axes1.append(axis1)
        #--- End: for
        
        if transpose_axes1 != data_axes1: 
            if not copied:
                other = other.copy()
                copied = True

            other.transpose(transpose_axes1, inplace=True)

        # ------------------------------------------------------------
        # Insert size 1 axes into other.data to match axes in
        # self.data which other.data doesn't have.
        #
        # For example, if   self.data is       P T Z Y X A
        #              and  other.data is        T   Y X
        #              then other.data becomes 1 T 1 Y X 1
        # ------------------------------------------------------------
        expand_positions1 = []
        for i, axis0 in enumerate(data_axes0):
            identity = s['axis_to_id'][axis0]
            if identity in matching_ids:
                axis1 = v['id_to_axis'][identity]
                if axis1 not in data_axes1:
                    expand_positions1.append(i)
            else:     
                expand_positions1.append(i)
        #--- End: for

        if expand_positions1:
            if not copied:
                other = other.copy()
                copied = True

            for i in expand_positions1:
                new_axis = other.set_construct(other._DomainAxis(1))
                other.insert_dimension(new_axis, position=i, inplace=True)
        #--- End: if

        # ----------------------------------------------------------------
        # Make sure that each pair of matching axes has the same
        # direction
        # ----------------------------------------------------------------
        flip_axes1 = []
        for identity in matching_ids:
            axis1 = v['id_to_axis'][identity]
            axis0 = s['id_to_axis'][identity]
            if other.direction(axis1) != self.direction(axis0):
                flip_axes1.append(axis1)
         #--- End: for

        if flip_axes1:
            if not copied:
                other = other.copy()
                copied = True

            other.flip(flip_axes1, inplace=True)

        return other


    def _equivalent_construct_data(self, field1, key0=None, key1=None,
                                   s=None, t=None,
                                   atol=None, rtol=None,
                                   verbose=False):
        '''TODO


    Two real numbers ``x`` and ``y`` are considered equal if
    ``|x-y|<=atol+rtol|y|``, where ``atol`` (the tolerance on absolute
    differences) and ``rtol`` (the tolerance on relative differences)
    are positive, typically very small numbers. See the *atol* and
    *rtol* parameters.
    
    
    :Parameters:
            
        key0: `str`
    
        key1: `str`
    
        field1: `Field`
    
        s: `dict`, optional
    
        t: `dict`, optional
    
        atol: `float`, optional
            The tolerance on absolute differences between real
            numbers. The default value is set by the `ATOL` function.
    
        rtol: `float`, optional
            The tolerance on relative differences between real
            numbers. The default value is set by the `RTOL` function.
    
        traceback: `bool`, optional
            If `True` then print a traceback highlighting where the two
            items differ.

        '''
#        self_Items = self.Items
#        field1_Items = field1.Items

        item0 = self.constructs[key0]
        item1 = field1.constructs[key1]
       
        if item0.has_data() != item1.has_data():
            if verbose:
                print("{0}: Only one item has data".format(
                    self.__class__.__name__)) # pragma: no cover
            return False
        
        if not item0.has_data():
            # Neither field has a data array
            return True

        if item0.size != item1.size:
            if verbose:
                print("{}: Different data array sizes ({}, {})".format(
                    self.__class__.__name__, item0.size, item1.size)) # pragma: no cover
            return False

        if item0.ndim != item1.ndim:
            if verbose:
                print("{0}: Different data array ranks ({1}, {2})".format(
                    self.__class__.__name__, item0.ndim, item1.ndim)) # pragma: no cover
            return False

        axes0 = self.get_data_axes(key0, default=())
        axes1 = field1.get_data_axes(key1, default=())
        
        if s is None:
            s = self.analyse_items()
        if t is None:
            t = field1.analyse_items()

#        axis_map = self.constructs.equals(field1.constructs,
#                                          _return_axis_map=True)

        transpose_axes = []
        for axis0 in axes0:
            axis1 = t['id_to_axis'].get(s['axis_to_id'][axis0], None)
            if axis1 is None:
                if verbose:
                    print("%s: TTTTTTTTTTT w2345nb34589*D*& TODO" % self.__class__.__name__) # pragma: no cover
                return False

            transpose_axes.append(axes1.index(axis1))

#        transpose_axes = []
#        for axis0 in axes0:
#            axis1 = axis_map.get(axis0)
#            if axis1 is None:
#                if verbose:
#                    print(
#                        "{}: Domain axis {!r} has no corresponding domain axis in other field".format(
#                        self.__class__.__name__, axis0))
#                                        
#                    print("%s: TODO" % self.__class__.__name__) # pragma: no cover
#                return False
#
#            try:
#                transpose_axes.append(axes1.index(axis1))
#            except ValueError:                
#                if verbose:
#                    print(
#                        "{}: In other field, domain axis {!r} is not spanned by {!r}".format(
#                            self.__class__.__name__, axis1, item1))
#                return False
#        #--- End: for
                
        copy1 = True

        if transpose_axes != list(range(item1.ndim)):
            if copy1:
                item1 = item1.copy()
                copy1 = False
                
            item1.transpose(transpose_axes, inplace=True)

        if item0.shape != item1.shape:
            # add traceback TODO
            return False

#        direction0 = self_Items.direction
#        direction1 = field1_Items.direction
        
        flip_axes = [i
                     for i, (axis1, axis0) in enumerate(zip(axes1, axes0))
                     if field1.direction(axis1) != self.direction(axis0)]
        
        if flip_axes:
            if copy1:
                item1 = item1.copy()                
                copy1 = False
                
            item1.flip(flip_axes, inplace=True)
        
        if not item0._equivalent_data(item1, rtol=rtol, atol=atol,
                                      verbose=verbose):
            # add traceback TODO
            return False
            
        return True

    # ----------------------------------------------------------------
    # Worker functions for regridding
    # ----------------------------------------------------------------
    def _regrid_get_latlong(self, name, axes=None):
        '''Retrieve the latitude and longitude coordinates of this field and
    associated information. If 1D lat/long coordinates are found then
    these are returned. Otherwise, 2D lat/long coordinates are
    searched for and if found returned.

    :Parameters:
    
        name: `str`
            A name to identify the field in error messages.
    
        axes: `dict`, optional
            A dictionary specifying the X and Y axes, with keys 'X' and
            'Y'.
    
    :Returns:
    
        axis_keys: `list`
            The keys of the x and y dimension coodinates.
        
        axis_sizes: `list`
            The sizes of the x and y dimension coordinates.
    
        coord_keys: `list`
            The keys of the x and y coordinate (1D dimension coordinate,
            or 2D auxilliary coordinates).
        
        coords: `list`
            The x and y coordinates (1D dimension coordinates or 2D
            auxilliary coordinates).
    
        coords_2D: `bool`
            True if 2D auxiliary coordinates are returned or if 1D X and Y
            coordinates are returned, which are not long/lat.

        '''
        if axes is None:
            # Retrieve the field's X and Y dimension coordinates
            xdims = self.dimension_coordinates('X')
            len_x = len(xdims)
            if not len_x:
                raise ValueError('No X dimension coordinate found for the ' +
                                 name + ' field. If none is present you ' +
                                 'may need to specify the axes keyword, ' +
                                 'otherwise you may need to set the X ' +
                                 'attribute of the X dimension coordinate ' +
                                 'to True.')

            if len_x > 1:
                raise ValueError(
                    "{} field has multiple 'X' dimension coordinates".format(
                        name))

            ydims = self.dimension_coordinates('Y')
            len_y = len(ydims)
            
            if not len_y:
                raise ValueError('No Y dimension coordinate found for the ' +
                                 name + ' field. If none is present you ' +
                                 'may need to specify the axes keyword, ' +
                                 'otherwise you may need to set the Y ' +
                                 'attribute of the Y dimension coordinate ' +
                                 'to True.')

            if len_y > 1:
                raise ValueError(
                    "{} field has multiple 'Y' dimension coordinates".format(
                        name))

            x = xdims.value()
            y = ydims.value()
            x_key = xdims.key()
            y_key = ydims.key()
            x_axis = self.domain_axis(x_key, key=True)
            y_axis = self.domain_axis(y_key, key=True)
            
#            x_axis, x = dict(x).popitem()
#            y_axis, y = dict(y).popitem()
#            x_key = x_axis
#            y_key = y_axis        
            x_size = x.size
            y_size = y.size
        else:
            try:
                x_axis = self.domain_axis(axes['X'], key=True, default=None)
            except KeyError:
                raise ValueError("Key 'X' must be specified for axes of " +
                                 name + " field.")

            if x_axis is None:
                raise ValueError('X axis specified for ' + name +
                                 ' field not found.')

            try:
                y_axis = self.domain_axis(axes['Y'], key=True, default=None)
            except KeyError:
                raise ValueError("Key 'Y' must be specified for axes of " +
                                 name + " field.")

            if y_axis is None:
                raise ValueError('Y axis specified for ' + name +
                                 ' field not found.')

            x_size = self.domain_axes[x_axis].get_size()
            y_size = self.domain_axes[y_axis].get_size()
        #--- End: if

        axis_keys  = [x_axis, y_axis]
        axis_sizes = [x_size, y_size]

        # If 1D latitude and longitude coordinates for the field are not found
        # search for 2D auxiliary coordinates.
        if (axes is not None or
            not x.Units.islongitude or            
            not y.Units.islatitude):
            lon_found = False
            lat_found = False
            for key, aux in self.auxiliary_coordinates.filter_by_naxes(2).items():
                if aux.Units.islongitude:
                    if lon_found:
                        raise ValueError('The 2D auxiliary longitude' +
                                         ' coordinate of the ' + name +
                                         ' field is not unique.')
                    else:
                        lon_found = True
                        x = aux
                        x_key = key
                #--- End: if
                
                if aux.Units.islatitude:
                    if lat_found:
                        raise ValueError('The 2D auxiliary latitude' +
                                         ' coordinate of the ' + name +
                                         ' field is not unique.')
                    else:
                        lat_found = True
                        y = aux
                        y_key = key
            #--- End: for
            
            if not lon_found or not lat_found:
                raise ValueError('Both longitude and latitude ' +
                                 'coordinates were not found for the ' +
                                 name + ' field.')

            if axes is not None:
                if set(axis_keys) != set(self.get_data_axes(x_key)):
                    raise ValueError('Axes of longitude do not match ' +
                                     'those specified for ' + name + 
                                     ' field.')

                if set(axis_keys) != set(self.get_data_axes(y_key)):
                    raise ValueError('Axes of latitude do not match ' +
                                     'those specified for ' + name +
                                     ' field.')
            #--- End: if
            coords_2D = True
        else:
            coords_2D = False
            # Check for size 1 latitude or longitude dimensions
            if x_size == 1 or y_size == 1:
                raise ValueError('Neither the longitude nor latitude' +
                                 ' dimension coordinates of the ' + name +
                                 ' field can be of size 1.')
        #--- End: if
        
        coord_keys = [x_key, y_key]
        coords = [x, y]
        return axis_keys, axis_sizes, coord_keys, coords, coords_2D


    def _regrid_get_cartesian_coords(self, name, axes):
        '''Retrieve the specified cartesian dimension coordinates of the field
    and their corresponding keys.
 
    :Parameters:
    
        name: `str`
            A name to identify the field in error messages.
    
        axes: sequence of `str`
            Specifiers for the dimension coordinates to be retrieved. See
            cf.Field.axes for details.
    
    :Returns:
    
        axis_keys: `list`
            A list of the keys of the dimension coordinates retrieved.
    
        coords: `list`
            A list of the dimension coordinates retrieved.

        '''
        axis_keys = []
        for axis in axes:
            key = self.domain_axis(axis, key=True)
            axis_keys.append(key)
#            tmp = self.axes(axis).keys()
#            len_tmp = len(tmp)
#            if not len_tmp:
#                raise ValueError('No ' + name + ' axis found: ' + str(axis))
#            elif len(tmp) != 1:
#                raise ValueError('Axis of ' + name + ' must be unique: ' +
#                                 str(axis))
#
#            axis_keys.append(tmp.pop())
        
        coords = []
        for key in axis_keys:
#            d = self.dim(key)
            d = self.dimension_coordinate(key, default=None)
            if d is None:
                raise ValueError('No unique ' + name + ' dimension coordinate ' +
                                 'matches key ' + key + '.')

            coords.append(d.copy())
        
        return axis_keys, coords


    def _regrid_get_axis_indices(self, axis_keys, i=False):
        '''Get axis indices and their orders in rank of this field.

    :Parameters:
    
        axis_keys: sequence
            A sequence of axis specifiers.
            
        i: `bool`, optional
            Whether to change the field in place or not.
    
    :Returns:
    
        axis_indices: list
            A list of the indices of the specified axes.
            
        order: ndarray
            A numpy array of the rank order of the axes.

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, '_regrid_get_axis_indices',
                                      {'i': i}) # pragma: no cover

        # Get the positions of the axes
        axis_indices = []
        for axis_key in axis_keys:
            try:
                axis_index = self.get_data_axes().index(axis_key)
            except ValueError:
                self.insert_dimension(axis_key, position=0, inplace=True)
                axis_index = self.get_data_axes().index(axis_key)
                
            axis_indices.append(axis_index)
                    
        # Get the rank order of the positions of the axes
        tmp = numpy_array(axis_indices)
        tmp = tmp.argsort()
        order = numpy_empty((len(tmp),), dtype=int)
        order[tmp] = numpy_arange(len(tmp))
        
        return axis_indices, order


    def _regrid_get_coord_order(self, axis_keys, coord_keys):
        '''Get the ordering of the axes for each N-D auxiliary coordinate.

    :Parameters:
    
        axis_keys: sequence
            A sequence of axis keys.
            
        coord_keys: sequence
            A sequence of keys for each ot the N-D auxiliary
            coordinates.
            
    :Returns:
    
        `list`
            A list of lists specifying the ordering of the axes for
            each N-D auxiliary coordinate.
    
        '''
        coord_axes = [self.get_data_axes(coord_key) for coord_key in coord_keys]
        coord_order = [[coord_axis.index(axis_key) for axis_key in axis_keys]
                       for coord_axis in coord_axes]
        return coord_order


    def _regrid_get_section_shape(self, axis_sizes, axis_indices):
        '''Get the shape of each regridded section.

    :Parameters:
    
        axis_sizes: sequence
            A sequence of the sizes of each axis along which the section.
            will be taken
            
        axis_indices: sequence
            A sequence of the same length giving the axis index of each
            axis.
            
    :Returns:
        
        shape: `list`
            A list defining the shape of each section.
        
        '''
        
        shape = [1] * self.data.ndim
        for i, axis_index in enumerate(axis_indices):
            shape[axis_index] = axis_sizes[i]
        
        return shape


    @classmethod
    def _regrid_check_bounds(cls, src_coords, dst_coords, method, ext_coords=None):
        '''Check the bounds of the coordinates for regridding and reassign the
    regridding method if auto is selected.
        
    :Parameters:
    
        src_coords: sequence
            A sequence of the source coordinates.
            
        dst_coords: sequence
            A sequence of the destination coordinates.
            
        method: `str`
            A string indicating the regrid method.
            
        ext_coords: `None` or sequence
            If a sequence of extension coordinates is present these
            are also checked. Only used for cartesian regridding when
            regridding only 1 (only 1!) dimension of a n>2 dimensional
            field. In this case we need to provided the coordinates of
            the the dimensions that aren't being regridded (that are
            the same in both src and dst grids) so that we can create
            a sensible ESMF grid object.
            
    :Returns:
    
        `None`

        '''
        
#        if method == 'auto':
#            method = 'conservative'
#            for coord in src_coords:
#                if not coord.hasbounds or not coord.contiguous(overlap=False):
#                    method = 'bilinear'
#                    break
#            #--- End: for
#            for coord in dst_coords:
#                if not coord.hasbounds or not coord.contiguous(overlap=False):
#                    method = 'bilinear'
#                    break
#            #--- End: for
#            if ext_coords is not None:
#                for coord in ext_coords:
#                    if (not coord.hasbounds or
#                        not coord.contiguous(overlap=False)):
#                        method = 'bilinear'
#                        break
#                #--- End: for
#            #--- End: if
        if method in ('conservative', 'conservative_1st', 'conservative_2nd'):
            for coord in src_coords:
                if not coord.has_bounds() or not coord.contiguous(overlap=False):
                    raise ValueError('Source coordinates must have' +
                                     ' contiguous, non-overlapping bounds' +
                                     ' for conservative regridding.')
            #--- End: for

            for coord in dst_coords:
                if not coord.has_bounds() or not coord.contiguous(overlap=False):
                    raise ValueError('Destination coordinates must have' +
                                     ' contiguous, non-overlapping bounds' +
                                     ' for conservative regridding.')
            #--- End: for

            if ext_coords is not None:
                for coord in ext_coords:
                    if (not coord.has_bounds() or
                        not coord.contiguous(overlap=False)):
                        raise ValueError('Dimension coordinates must have' +
                                         ' contiguous, non-overlapping bounds' +
                                         ' for conservative regridding.')
                #--- End: for
            #--- End: if
        #--- End: if

#        return method


    @classmethod
    def _regrid_check_method(cls, method):
        '''Check the regrid method is valid and if not raise an error.

    :Parameters:
    
        method: `str`
            The regridding method.

        '''
        if method is None:
            raise ValueError("Can't regrid: Must select a regridding method")

        if method not in ('conservative_2nd', 'conservative_1st', 'conservative',
                          'patch', 'bilinear', 'nearest_stod', 'nearest_dtos'):
            raise ValueError("Can't regrid: Invalid method: {!r}".format(method))


    @classmethod
    def _regrid_check_use_src_mask(cls, use_src_mask, method):
        '''Check that use_src_mask is True for all methods other than
    nearest_stod and if not raise an error.

    :Parameters:
    
        use_src_mask: `bool`
            Whether to use the source mask in regridding.
    
        method: `str`
            The regridding method.
    
        '''
        if not use_src_mask and not method == 'nearest_stod':
            raise ValueError('use_src_mask can only be False when using the ' +
                             'nearest_stod method.')

    
    def _regrid_get_reordered_sections(self, axis_order, regrid_axes,
                                       regrid_axis_indices):
        '''Get a dictionary of the data sections for regridding and a list of
    its keys reordered if necessary so that they will be looped over
    in the order specified in axis_order.

    :Parameters:
    
        axis_order: `None` or sequence of axes specifiers.
            If `None` then the sections keys will not be reordered. If
            a particular axis is one of the regridding axes or is not
            found then a ValueError will be raised.
            
        regrid_axes: sequence
            A sequence of the keys of the regridding axes.
        
        regrid_axis_indices: sequence
            A sequence of the indices of the regridding axes.
                
    :Returns:
    
        section_keys: `list`
            An ordered list of the section keys.
    
        sections: `dict`
            A dictionary of the data sections for regridding.

        '''

# If we had dynamic masking, we wouldn't need this method, we could
# sdimply replace it in regrid[sc] with a call to
# Data.section. However, we don't have it, so this allows us to
# possibibly reduce the number of trasnistions between different masks
# - each change is slow.
        
        axis_indices = []
        if axis_order is not None:
            for axis in axis_order:
#                axis_key = self.dim(axis, key=True)
                axis_key = self.dimension_coordinates.filter_by_axis('exact', axis_key).key(None)
                if axis_key is not None:
                    if axis_key in regrid_axes:
                        raise ValueError('Cannot loop over regridding axes.')

                    try:
                        axis_indices.append(self.get_data_axes().index(axis_key))
                    except ValueError:
                        # The axis has been squeezed so do nothing
                        pass 

                else:
                    raise ValueError('Axis not found: ' + str(axis))    
        #--- End: if
        
        # Section the data
        sections = self.data.section(regrid_axis_indices)
        
        # Reorder keys correspondingly if required
        if axis_indices:
            section_keys = sorted(sections.keys(),
                                  key=operator_itemgetter(*axis_indices))
        else:
            section_keys = sections.keys()
        
        return section_keys, sections


    def _regrid_get_destination_mask(self, dst_order, axes=('X', 'Y'),
                                     cartesian=False, coords_ext=None):
        '''Get the mask of the destination field.

    :Parameters:
    
        dst_order: sequence, optional
            The order of the destination axes.
        
        axes: optional
            The axes the data is to be sectioned along.
        
        cartesian: `bool`, optional
            Whether the regridding is Cartesian or spherical.
        
        coords_ext: sequence, optional
            In the case of Cartesian regridding, extension coordinates
            (see _regrid_check_bounds for details).
    
    :Returns:
    
        dst_mask: ndarray
            A numpy array with the mask.

        '''
        dst_mask = self.section(axes, stop=1,
                                ndim=1)[0].squeeze().array.mask
        dst_mask = dst_mask.transpose(dst_order)
        if cartesian:
            tmp = []
            for coord in coords_ext:
                tmp.append(coord.size)
                dst_mask = numpy_tile(dst_mask, tmp + [1]*dst_mask.ndim)
        #--- End: if
        
        return dst_mask


    def _regrid_fill_fields(self, src_data, srcfield, dstfield):
        '''Fill the source field with data and the destination field with fill
    values.
    
    :Parameters:
        
        src_data: ndarray
            The data to fill the source field with.
            
        srcfield: ESMPy Field
            The source field.
            
        dstfield: ESMPy Field
            The destination field. This get always gets initialised with
            missing values.
    
        '''
        srcfield.data[...] = numpy_ma_MaskedArray(src_data, copy=False).filled(self.fill_value(default='netCDF'))
        dstfield.data[...] = self.fill_value(default='netCDF')

        
    def _regrid_compute_field_mass(self, _compute_field_mass, k,
                                   srcgrid, srcfield, srcfracfield, dstgrid,
                                   dstfield):
        '''Compute the field mass for conservative regridding. The mass should
    be the same before and after regridding.
    
    :Parameters:
    
        _compute_field_mass: `dict`
            A dictionary for the results.
        
        k: `tuple`
            A key identifying the section of the field being regridded.
            
        srcgrid: ESMPy grid
            The source grid.
            
        srcfield: ESMPy grid
            The source field.
            
        srcfracfield: ESMPy field
            Information about the fraction of each cell of the source
            field used in regridding.
            
        dstgrid: ESMPy grid
            The destination grid.
            
        dstfield: ESMPy field
            The destination field.
    
        '''
        if not type(_compute_field_mass) == dict:
            raise ValueError('Expected _compute_field_mass to be a dictionary.')
        
        # Calculate the mass of the source field
        srcareafield = Regrid.create_field(srcgrid, 'srcareafield')
        srcmass = Regrid.compute_mass_grid(srcfield, srcareafield, dofrac=True, 
            fracfield=srcfracfield, uninitval=self.fill_value(default='netCDF'))
        
        # Calculate the mass of the destination field
        dstareafield = Regrid.create_field(dstgrid, 'dstareafield')
        dstmass = Regrid.compute_mass_grid(dstfield, dstareafield, 
            uninitval=self.fill_value(default='netCDF'))
        
        # Insert the two masses into the dictionary for comparison
        _compute_field_mass[k] = (srcmass, dstmass)


    def _regrid_get_regridded_data(self, method, fracfield, dstfield,
                                   dstfracfield):
        '''Get the regridded data of frac field as a numpy array from the
    ESMPy fields.
    
    :Parameters:
    
        method: `str`
            The regridding method.
            
        fracfield: `bool`
            Whether to return the frac field or not in the case of
            conservative regridding.
            
        dstfield: ESMPy field
            The destination field.
            
        dstfracfield: ESMPy field
            Information about the fraction of each of the destination
            field cells involved in the regridding. For conservative
            regridding this must be taken into account.

        '''
        if method in ('conservative', 'conservative_1st', 'conservative_2nd'):
            frac = dstfracfield.data[...].copy()
            if fracfield:
                regridded_data = frac
            else:
                frac[frac == 0.0] = 1.0
                regridded_data = numpy_ma_MaskedArray(dstfield.data[...].copy()/frac, 
                    mask=(dstfield.data == self.fill_value(default='netCDF')))
        else:            
            regridded_data = numpy_ma_MaskedArray(dstfield.data[...].copy(), 
                mask=(dstfield.data == self.fill_value(default='netCDF')))

        return regridded_data


    def _regrid_update_coordinate_references(self, dst, src_axis_keys,
                                             method, use_dst_mask,
                                             cartesian=False,
                                             axes=('X', 'Y'),
                                             n_axes=2,
                                             src_cyclic=False,
                                             dst_cyclic=False):
        '''Update the coordinate references of the new field after regridding.

    :Parameters:
    
        dst: `Field` or `dict`
            The object with the destination grid for regridding.
        
        src_axis_keys: sequence of `str`
            The keys of the source regridding axes.
            
        method: `bool`
            The regridding method.
            
        use_dst_mask: `bool`
            Whether to use the destination mask in regridding.
            
        i: `bool`
            Whether to do the regridding in place.
            
        cartesian: `bool`, optional
            Whether to do Cartesian regridding or spherical
            
        axes: sequence, optional
            Specifiers for the regridding axes.
            
        n_axes: `int`, optional
            The number of regridding axes.
            
        src_cyclic: `bool`, optional
            Whether the source longitude is cyclic for spherical
            regridding.
            
        dst_cyclic: `bool`, optional
            Whether the destination longitude is cyclic for
            spherical regridding.

        '''
        for key, ref in self.coordinate_references.items():
#            ref_axes = self.axes(ref.coordinates, exact=True) # v2
            ref_axes = []
            for k in ref.coordinates():
                ref_axes.extend(self.get_data_axes(k))                
            
            if set(ref_axes).intersection(src_axis_keys):
                self.remove_item(key)
                continue

            for term, value in ref.coordinate_conversion.domain_ancillaries().items():
#                key = self.domain_anc(value, key=True) # v2
                key = self.domain_ancillaries(value).key(default=None)
                if key is None:
                    continue

                # If this domain ancillary spans both X and Y axes
                # then regrid it, otherwise remove it
#                if f.domain_anc(key, axes_all=('X', 'Y')):# v2
                x = self.domain_axis('X', key=True)
                y = self.domain_axis('Y', key=True)
                if f.domain_ancillaries.filter_by_key(key).filter_by_axis('exact', x, y):
                    # Convert the domain ancillary into an independent
                    # field
                    value = self.convert(key)
                    try:
                        if cartesian:
                            new_value = value.regridc(dst, axes=axes,
                                                      method=method,
                                                      use_dst_mask=use_dst_mask,
                                                      inplace=True)
                        else:
                            new_value = value.regrids(dst,
                                                      src_cyclic=src_cyclic,
                                                      dst_cyclic=dst_cyclic,
                                                      method=method,
                                                      use_dst_mask=use_dst_mask,
                                                      inplace=True)
                    except ValueError:
                        ref[term] = None
#                        self.remove_item(key)
                        self.del_construct(key)
                    else:
                        ref[term] = key
                        d_axes = self.axes(key)
#                        self.remove_item(key)
                        self.del_construct(key)
#                        self.remove_item(key)
                        self.insert_domain_anc(new_value, key=key, axes=d_axes, copy=False)
                #--- End: if
            #--- End: for
        #--- End: for

        
    def _regrid_copy_coordinate_references(self, dst, dst_axis_keys):
        '''Copy coordinate references from the destination field to the new,
    regridded field.
    
    :Parameters:
    
        dst: `Field`
            The destination field.
            
        dst_axis_keys: sequence of `str`
            The keys of the regridding axes in the destination field.
    
    :Returns:
    
        `None`

        '''
        for ref in dst.coordinate_references.values():
            axes = set()
            for key in ref.coordinates():
                axes.update(dst.get_data_axes(key))
            
#            axes = dst.axes(ref.coordinates(), exact=True)
            if axes and set(axes).issubset(dst_axis_keys):
                # This coordinate reference's coordinates span the X
                # and/or Y axes
                
#                self.insert_ref(dst._unconform_ref(ref), copy=False)
#                self.set_construct(dst._unconform_coordinate_reference(ref),
#                                   copy=False)
                self.set_coordinate_reference(ref, field=dst, strict=True)                


    @classmethod
    def _regrid_use_bounds(cls, method):
        '''Returns whether to use the bounds or not in regridding. This is
    only the case for conservative regridding.
    
    :Parameters:
    
        method: `str`
            The regridding method
    
    :Returns:
    
        `bool`

        '''
        return method in ('conservative', 'conservative_1st', 'conservative_2nd')


    def _regrid_update_coordinates(self, dst, dst_dict, dst_coords,
                                   src_axis_keys, dst_axis_keys,
                                   cartesian=False,
                                   dst_axis_sizes=None,
                                   dst_coords_2D=False,
                                   dst_coord_order=None):
        '''Update the coordinates of the new field.

    :Parameters:
    
        dst: Field or `dict`
            The object containing the destination grid.
        
        dst_dict: `bool`
            Whether dst is a dictionary.
            
        dst_coords: sequence
            The destination coordinates.
            
        src_axis_keys: sequence
            The keys of the regridding axes in the source field.
            
        dst_axis_keys: sequence
            The keys of the regridding axes in the destination field.
            
        cartesian: `bool`, optional
            Whether regridding is Cartesian of spherical, False by
            default.
            
        dst_axis_sizes: sequence, optional
            The sizes of the destination axes.
            
        dst_coords_2D: `bool`, optional
            Whether the destination coordinates are 2D, currently only
            applies to spherical regridding.
            
        dst_coord_order: `list`, optional
            A list of lists specifying the ordering of the axes for
            each 2D destination coordinate.

        '''
# NOTE: May be common ground between cartesian and shperical that
# could save some lines of code.

        # Remove the source coordinates of new field
#        self.remove_items(axes=src_axis_keys)
        for key in self.constructs.filter_by_axis('or', *src_axis_keys):
            self.del_construct(key)
            
        if cartesian:
            # Make axes map
            if not dst_dict:
                axis_map = {}
                for k_s, k_d in zip(src_axis_keys, dst_axis_keys):
                    axis_map[k_d] = k_s
            #--- End: if
            
            # Insert coordinates from dst into new field
            if dst_dict:
                for k_s, d in zip(src_axis_keys, dst_coords):
                    self.domain_axes[k_s].set_size(d.size)
                    self.set_construct(d, axes=[k_s])
            else:
                for k_d in dst_axis_keys:
                    d = dst.dimension_coordinate(k_d)
                    k_s = axis_map[k_d]
                    self.domain_axes[k_s].set_size(d.size)
                    self.set_construct(d, axes=[k_s])

                for aux_key, aux in dst.auxiliary_coordinates.filter_by_axis(
                        'subset', *dst_axis_keys).items():
                    aux_axes = [axis_map[k_d] for k_d in dst.get_data_axes(aux_key)]
                    self.set_construct(aux, axes=aux_axes)
        else:
            # Give destination grid latitude and longitude standard names
            dst_coords[0].standard_name = 'longitude'
            dst_coords[1].standard_name = 'latitude'
            
            # Insert 'X' and 'Y' coordinates from dst into new field
            for axis_key, axis_size in zip(src_axis_keys, dst_axis_sizes):
                self.domain_axes[axis_key].set_size(axis_size)

            if dst_dict:
                if dst_coords_2D:
                    for coord, coord_order in zip(dst_coords, dst_coord_order):
                        axis_keys = [src_axis_keys[index] for index in coord_order]
                        self.set_construct(coord, axes=axis_keys)
                else:
                    for coord, axis_key in zip(dst_coords, src_axis_keys):
                        self.set_construct(coord, axes=[axis_key])
            else:
                for src_axis_key, dst_axis_key in zip(src_axis_keys, dst_axis_keys):
                    try:                        
                        self.set_construct(dst.dimension_coordinate(dst_axis_key),
                                           axes=[src_axis_key])
                    except AttributeError:
                        pass

                    for aux in dst.auxiliary_coordinates.filter_by_axis(
                            'exact', dst_axis_key).values():
                        self.set_construct(aux, axes=[src_axis_key])
                #--- End: for

                for aux_key, aux in dst.auxiliary_coordinates.filter_by_axis(
                        'exact', *dst_axis_keys).items():
                    aux_axes = dst.get_data_axes(aux_key)
                    if aux_axes == tuple(dst_axis_keys):
                        self.set_construct(aux, axes=src_axis_keys)
                    else:
                        self.set_construct(aux, axes=src_axis_keys[::-1])
                #--- End: for
            #--- End: if
        #--- End: if

        # Copy names of dimensions from destination to source field
        if not dst_dict:
            for src_axis_key, dst_axis_key in zip(src_axis_keys, dst_axis_keys):
                ncdim = dst.domain_axes[dst_axis_key].nc_get_dimension(None)
                if ncdim is not None:
                    self.domain_axes[src_axis_key].nc_set_dimension(ncdim)
        #--- End: if
        

    # ----------------------------------------------------------------
    # End of worker functions for regridding
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # Attributes
    # ----------------------------------------------------------------
    @property
    def DSG(self):
        '''True if the field contains a collection of discrete sampling
geomtries.

.. versionadded:: 2.0

.. seealso:: `featureType`

**Examples:**

>>> f.featureType
'timeSeries'
>>> f.DSG
True

>>> f.get_property('featureType', 'NOT SET')
NOT SET
>>> f.DSG
False

        '''
        return self.has_property('featureType')
    #--- End: def

    @property
    def Flags(self):
        '''A `Flags` object containing self-describing CF flag values.

    Stores the `flag_values`, `flag_meanings` and `flag_masks` CF
    properties in an internally consistent manner.
    
    **Examples:**
    
    >>> f.Flags
    <CF Flags: flag_values=[0 1 2], flag_masks=[0 2 2], flag_meanings=['low' 'medium' 'high']>

        '''
        try:
            return self._custom['Flags']
        except KeyError:
            raise AttributeError("{!r} object has no attribute 'Flags'".format(
                self.__class__.__name__))
    @Flags.setter
    def Flags(self, value):
        self._custom['Flags'] = value
    @Flags.deleter
    def Flags(self):
        try:
            return self._custom.pop('Flags')
        except KeyError:
            raise AttributeError("{!r} object has no attribute 'Flags'".format(
                self.__class__.__name__))
    @property
    def ncdimensions(self):
        '''
        '''
        out = {}
        for dim, domain_axis in self.domain_axes.items():
            ncdim = domain_axis.nc_get_dimension(None)
            if ncdim is not None:
                out[dim] = ncdim
        #--- End: for
        
        return out


    @property
    def rank(self):
        '''The number of axes in the domain.

    Note that this may be greater the number of data array axes.
    
    .. seealso:: `ndim`, `unsqueeze`
    
    **Examples:**
    
    >>> print(f)
    air_temperature field summary
    -----------------------------
    Data           : air_temperature(time(12), latitude(64), longitude(128)) K
    Cell methods   : time: mean
    Axes           : time(12) = [ 450-11-16 00:00:00, ...,  451-10-16 12:00:00] noleap
                   : latitude(64) = [-87.8638000488, ..., 87.8638000488] degrees_north
                   : longitude(128) = [0.0, ..., 357.1875] degrees_east
                   : height(1) = [2.0] m
    >>> f.rank
    4
    >>> f.ndim
    3
    >>> f
    <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>
    >>> f.unsqueeze(inplace=True)
    <CF Field: air_temperature(height(1), time(12), latitude(64), longitude(128)) K>
    >>> f.rank
    4
    >>> f.ndim
    4

        '''
        return len(self.domain_axes)


    # ----------------------------------------------------------------
    # CF properties
    # ----------------------------------------------------------------
    @property
    def flag_values(self):
        '''The flag_values CF property.

    Provides a list of the flag values. Use in conjunction with
    `flag_meanings`. See http://cfconventions.org/latest.html for
    details.
    
    Stored as a 1-d numpy array but may be set as any array-like
    object.
    
    **Examples:**
    
    >>> f.flag_values = ['a', 'b', 'c']
    >>> f.flag_values
    array(['a', 'b', 'c'], dtype='|S1')
    >>> f.flag_values = numpy.arange(4)
    >>> f.flag_values
    array([1, 2, 3, 4])
    >>> del f.flag_values
    
    >>> f.set_property('flag_values', 1)
    >>> f.get_property('flag_values')
    array([1])
    >>> f.del_property('flag_values')

        '''
        try:
            return self.Flags.flag_values
        except AttributeError:
            raise AttributeError(
                "{!r} doesn't have CF property 'flag_values'".format(
                    self.__class__.__name__))

        
    @flag_values.setter
    def flag_values(self, value):
        try:
            flags = self.Flags
        except AttributeError:
            self.Flags = Flags(flag_values=value)
        else:
            flags.flag_values = value

            
    @flag_values.deleter
    def flag_values(self):
        try:
            del self.Flags.flag_values
        except AttributeError:
            raise AttributeError(
                "Can't delete non-existent %s CF property 'flag_values'" %
                self.__class__.__name__)
        else:
            if not self.Flags:
                del self.Flags


    @property
    def flag_masks(self):
        '''The flag_masks CF property.

    Provides a list of bit fields expressing Boolean or enumerated
    flags. See http://cfconventions.org/latest.html for details.
    
    Stored as a 1-d numpy array but may be set as array-like object.
    
    **Examples:**
    
    >>> f.flag_masks = numpy.array([1, 2, 4], dtype='int8')
    >>> f.flag_masks
    array([1, 2, 4], dtype=int8)
    >>> f.flag_masks = (1, 2, 4, 8)
    >>> f.flag_masks
    array([1, 2, 4, 8], dtype=int8)
    >>> del f.flag_masks
    
    >>> f.set_property('flag_masks', 1)
    >>> f.get_property('flag_masks')
    array([1])
    >>> f.del_property('flag_masks')

        '''
        try:
            return self.Flags.flag_masks
        except AttributeError:
            raise AttributeError(
                "{!r} doesn't have CF property 'flag_masks'".format(
                    self.__class__.__name__))        
    @flag_masks.setter
    def flag_masks(self, value):
        try:
            flags = self.Flags
        except AttributeError:
            self.Flags = Flags(flag_masks=value)
        else:
            flags.flag_masks = value

            
    @flag_masks.deleter
    def flag_masks(self):
        try:
            del self.Flags.flag_masks
        except AttributeError:
            raise AttributeError(
                "Can't delete non-existent {!r} CF property 'flag_masks'".format(
                    self.__class__.__name__))
        else:
            if not self.Flags:
                del self.Flags


    @property
    def flag_meanings(self):
        '''The flag_meanings CF property.

    Use in conjunction with `flag_values` to provide descriptive words
    or phrases for each flag value. If multi-word phrases are used to
    describe the flag values, then the words within a phrase should be
    connected with underscores. See
    http://cfconventions.org/latest.html for details.
    
    Stored as a 1-d numpy string array but may be set as a space
    delimited string or any array-like object.
    
    **Examples:**
    
    >>> f.flag_meanings = 'low medium      high'
    >>> f.flag_meanings
    array(['low', 'medium', 'high'],
          dtype='|S6')
    >>> del flag_meanings
    
    >>> f.flag_meanings = ['left', 'right']
    >>> f.flag_meanings
    array(['left', 'right'],
          dtype='|S5')
    
    >>> f.flag_meanings = 'ok'
    >>> f.flag_meanings
    array(['ok'],
          dtype='|S2')
    
    >>> f.set_property('flag_meanings', numpy.array(['a', 'b'])
    >>> f.get_property('flag_meanings')
    array(['a', 'b'],
          dtype='|S1')
    >>> f.del_property('flag_meanings')

        '''
        try:
            return ' '.join(self.Flags.flag_meanings)
        except AttributeError:
            raise AttributeError(
                "{!r} doesn't have CF property 'flag_meanings'".format(
                    self.__class__.__name__))
    @flag_meanings.setter
    def flag_meanings(self, value): 
        try: # TODO deal with space-delimited strings
            flags = self.Flags
        except AttributeError:
            self.Flags = Flags(flag_meanings=value) 
        else:
            flags.flag_meanings = value

            
    @flag_meanings.deleter
    def flag_meanings(self):
        try:
            del self.Flags.flag_meanings
        except AttributeError:
            raise AttributeError(
                "Can't delete non-existent {!r} CF property 'flag_meanings'".format(
                    self.__class__.__name__))
        else:
            if not self.Flags:
                del self.Flags


    @property 
    def Conventions(self):
        '''The Conventions CF property.

    The name of the conventions followed by the field. See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.Conventions = 'CF-1.6'
    >>> f.Conventions
    'CF-1.6'
    >>> del f.Conventions
    
    >>> f.set_property('Conventions', 'CF-1.6')
    >>> f.get_property('Conventions')
    'CF-1.6'
    >>> f.del_property('Conventions')

        '''
        return self.get_property('Conventions')


    @Conventions.setter
    def Conventions(self, value): self.set_property('Conventions', value)
    @Conventions.deleter
    def Conventions(self):        self.del_property('Conventions')


    @property
    def featureType(self):
        '''The featureType CF property.

    The type of discrete sampling geometry, such as ``point`` or
    ``timeSeriesProfile``. See http://cfconventions.org/latest.html
    for details.
    
    .. versionadded:: 2.0
    
    .. seealso:: `DSG` TODO
    
    **Examples:**
    
    >>> f.featureType = 'trajectoryProfile'
    >>> f.featureType
    'trajectoryProfile'
    >>> del f.featureType
    
    >>> f.set_property('featureType', 'profile')
    >>> f.get_property('featureType')
    'profile'
    >>> f.del_property('featureType')

        '''
        return self.get_property('featureType')


    @featureType.setter
    def featureType(self, value): self.set_property('featureType', value)
    @featureType.deleter
    def featureType(self):        self.del_property('featureType')


    @property
    def institution(self):
        '''The institution CF property.

    Specifies where the original data was produced. See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.institution = 'University of Reading'
    >>> f.institution
    'University of Reading'
    >>> del f.institution
    
    >>> f.set_property('institution', 'University of Reading')
    >>> f.get_property('institution')
    'University of Reading'
    >>> f.del_property('institution')

        '''
        return self.get_property('institution')

    
    @institution.setter
    def institution(self, value): self.set_property('institution', value)
    @institution.deleter
    def institution(self):        self.del_property('institution')


    @property
    def references(self):
        '''The references CF property.

    Published or web-based references that describe the data or
    methods used to produce it. See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.references = 'some references'
    >>> f.references
    'some references'
    >>> del f.references
    
    >>> f.set_property('references', 'some references')
    >>> f.get_property('references')
    'some references'
    >>> f.del_property('references')

        '''
        return self.get_property('references')

    
    @references.setter
    def references(self, value): self.set_property('references', value)
    @references.deleter
    def references(self):        self.del_property('references')


    @property
    def standard_error_multiplier(self):
        '''The standard_error_multiplier CF property.

    If a data variable with a `standard_name` modifier of
    ``'standard_error'`` has this attribute, it indicates that the values
    are the stated multiple of one standard error. See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.standard_error_multiplier = 2.0
    >>> f.standard_error_multiplier
    2.0
    >>> del f.standard_error_multiplier
    
    >>> f.set_property('standard_error_multiplier', 2.0)
    >>> f.get_property('standard_error_multiplier')
    2.0
    >>> f.del_property('standard_error_multiplier')

        '''
        return self.get_property('standard_error_multiplier')


    @standard_error_multiplier.setter
    def standard_error_multiplier(self, value):
        self.set_property('standard_error_multiplier', value)
    @standard_error_multiplier.deleter
    def standard_error_multiplier(self):
        self.del_property('standard_error_multiplier')


    @property
    def source(self):
        '''The source CF property.

    The method of production of the original data. If it was
    model-generated, `source` should name the model and its version,
    as specifically as could be useful. If it is observational,
    `source` should characterize it (for example, ``'surface
    observation'`` or ``'radiosonde'``). See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.source = 'radiosonde'
    >>> f.source
    'radiosonde'
    >>> del f.source
    
    >>> f.set_property('source', 'surface observation')
    >>> f.get_property('source')
    'surface observation'
    >>> f.del_property('source')

        '''
        return self.get_property('source')


    @source.setter
    def source(self, value): self.set_property('source', value)
    @source.deleter
    def source(self):        self.del_property('source')


    @property
    def title(self):
        '''The title CF property.

    A short description of the file contents from which this field was
    read, or is to be written to. See
    http://cfconventions.org/latest.html for details.
    
    **Examples:**
    
    >>> f.title = 'model data'
    >>> f.title
    'model data'
    >>> del f.title
    
    >>> f.set_property('title', 'model data')
    >>> f.get_property('title')
    'model data'
    >>> f.del_property('title')

        '''
        return self.get_property('title')

    
    @title.setter
    def title(self, value): self.set_property('title', value)
    @title.deleter
    def title(self):        self.del_property('title')


    # ----------------------------------------------------------------
    # Methods
    # ----------------------------------------------------------------
    def cell_area(self, radius=None, insert=False, force=False):
        '''Return a field containing horizontal cell areas.

    .. versionadded:: 1.0
    
    .. seealso:: `weights`
    
    :Parameters:
    
        radius: optional
            The radius used for calculating spherical surface areas
            when both of the horizontal axes are part of a spherical
            polar coordinate system. May be any numeric scalar object
            that can be converted to a `Data` object (which includes
            `numpy` and `Data` objects). If unset then the radius is
            either taken from the "earth_radius" parameter(s) of any
            coordinate reference construct datums, or, if no such
            parameter exisits, set to 6371229.0 metres (approximating
            the radius if Earth). If units are not specified then
            units of metres are assumed.
    
            *Parameter example:*         
              Five equivalent ways to set a radius of 6371200 metres:
              ``radius=6371200``, ``radius=numpy.array(6371200)``,
              ``radius=cf.Data(6371200)``, ``radius=cf.Data(6371200,
              'm')``, ``radius=cf.Data(6371.2, 'km')``.
    
        insert: `bool`, optional
            If `True` then the calculated cell areas are also inserted
            in place as an area cell measure object. An existing area
            cell measure object for the horizontal axes will not be
            overwritten.
    
        force: `bool`, optional
            If `True` the always calculate the cell areas. By default if
            there is already an area cell measure object for the
            horizontal axes then it will provide the area values.
            
    :Returns:
    
        `Field`
            A field construct containing the horizontal cell areas.
    
    **Examples:**
    
    >>> a = f.cell_area()
    >>> a = f.cell_area(force=True)
    >>> a = f.cell_area(radius=cf.Data(3389.5, 'km'))

        '''
        if insert:
            _DEPRECATION_ERROR_KWARGS(self, 'cell_area',
                                      {'insert': insert}) # pragma: no cover

        x_axis = self.domain_axis('X', key=True, default=None)
        y_axis = self.domain_axis('Y', key=True, default=None)
        area_clm = self.cell_measures.filter_by_measure('area').filter_by_axis(
            'exact', x_axis, y_axis)

        if not force and area_clm:
            w = self.weights('area')
        else:
            x = self.dimension_coordinate('X', default=None)
            y = self.dimension_coordinate('Y', default=None)
            if (x is None or y is None or 
                not x.Units.equivalent(_units_radians) or
                not y.Units.equivalent(_units_radians)):
                raise ValueError("Can't create cell areas: X or Y coordinates have incompatible units({!r}, {!r}). Expected units equivalent to radians".format(
                    x.Units, y.Units))
            
            # Got x and y coordinates in radians, so we can calculate.
    
            # Parse the radius of the planet
            if radius is None:
                default_radius = Data(6371229.0, 'm')
                
                radii = []
                for cr in self.coordinate_references.values():
                    r = cr.datum.get_parameter('earth_radius', None)
                    if r is not None:
                        r = Data.asdata(r)
                        if not r.Units:
                            r.override_units('m', inplace=True)
    
                        get = False
                        for _ in radii:
                            if r == _:
                                got = True
                                break
                        #--- End: for
    
                        if not got:
                            radii.append(r)
                #--- End: for
    
                if len(radii) > 1:
                    raise ValueError(
                        "Multiple radii found in coordinate reference constructs: {!r}".format(
                            radii))
                
                if len(radii) == 1:
                    radius = radii[0]                    
                else:
                    radius = default_radius
            #--- End: if
                
            radius = Data.asdata(radius).squeeze()
            radius.dtype = float
            if radius.size != 1:
                raise ValueError("Multiple radii: radius={!r}".format(radius))

            if not radius.Units:
                radius.override_units(_units_metres, inplace=True)
            elif not radius.Units.equivalent(_units_metres):
                raise ValueError(
                    "Invalid units for radius: {!r}".format(radius.Units))

            w = self.weights('area')
            radius **= 2
            w *= radius
            w.override_units(radius.Units, inplace=True)
        #--- End: if               

        w.standard_name = 'area'
        
        return w


    def map_axes(self, other):
        '''Map the axis identifiers of the field to their equivalent axis
    identifiers of another.
    
    :Parameters:
    
        other: `Field`
    
    :Returns:
    
        `dict`
            A dictionary whose keys are the axis identifiers of the
            field with corresponding values of axis identifiers of the
            of other field.
    
    **Examples:**
    
    >>> f.map_axes(g)
    {'dim0': 'dim1',
     'dim1': 'dim0',
     'dim2': 'dim2'}

        '''
        s = self.analyse_items()
        t = other.analyse_items()
        id_to_axis1 = t['id_to_axis']

        out = {}        
        for axis, identity in s['axis_to_id'].items():
            if identity in id_to_axis1:
                out[axis] = id_to_axis1[identity]

        return out


    def close(self):
        '''Close all files referenced by the field.

    Note that a closed file will be automatically reopened if its
    contents are subsequently required.
    
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> f.close()

        '''
        super().close()

        for construct in self.constructs.filter_by_data().values():
            construct.close()


    def iscyclic(self, identity, **kwargs):
        '''Returns True if the given axis is cyclic.

    .. versionadded:: 1.0
    
    .. seealso:: `axis`, `cyclic`, `period`
    
    :Parameters:
    
        identity:
           Select the domain axis construct by one of:
    
              * An identity or key of a 1-d coordinate construct that
                whose data spans the domain axis construct.
    
              * A domain axis construct identity or key.
    
              * The position of the domain axis construct in the field
                construct's data.
    
            The *identity* parameter selects the domain axis as
            returned by this call of the field's `domain_axis` method:
            ``f.domain_axis(identity)``.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `bool`
            True if the selected axis is cyclic, otherwise False.
            
    **Examples:**
    
    >>> f.iscyclic('X')
    True
    >>> f.iscyclic('latitude')
    False

    >>> x = f.iscyclic('long_name=Latitude')
    >>> x = f.iscyclic('dimensioncoordinate1')
    >>> x = f.iscyclic('domainaxis2')
    >>> x = f.iscyclic('key%domainaxis2')
    >>> x = f.iscyclic('ncdim%y')
    >>> x = f.iscyclic(2)

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'iscyclic', kwargs) # pragma: no cover

        axis = self.domain_axis(identity, key=True, default=None)
        if axis is None:
            raise ValueError(
                "Can't identify unique axis from identity {!r}".format(identity))

        return axis in self.cyclic()


    @classmethod
    def concatenate(cls, fields, axis=0, _preserve=True):
        '''Join a sequence of fields together.

    This is different to `cf.aggregate` because it does not account
    for all metadata. For example, it assumes that the axis order is
    the same in each field.
    
    .. versionadded:: 1.0
    
    .. seealso:: `cf.aggregate`, `Data.concatenate`
    
    :Parameters:
    
        fields: `FieldList`
            TODO

        axis: `int`, optional
            TODO

    :Returns:
    
        `Field`
            TODO

        '''         
        if isinstance(fields, Field):
            return fields.copy()

        field0 = fields[0]
        out = field0.copy()

        if len(fields) == 1:
            return out
        
        new_data = Data.concatenate([f.get_data() for f in fields],
                                    axis=axis,
                                    _preserve=_preserve)
        
#        out = super(cls, field0).concatenate(fields, axis=axis,
#                                             _preserve=_preserve)
            
        # Change the domain axis size
        dim = out.get_data_axes()[axis]        
        out.set_construct(DomainAxis(size=new_data.shape[axis]), key=dim)
#        out.insert_axis(DomainAxis(out.shape[axis]), key=dim, replace=True)

        # Insert the concatenated data
        out.set_data(new_data, set_axes=False, copy=False)
                
        # ------------------------------------------------------------
        # Concatenate constructs with data
        # ------------------------------------------------------------
        for key, construct in field0.constructs.filter_by_data().items():
            construct_axes = field0.get_data_axes(key)

            if dim not in construct_axes:
                # This construct does not span the concatenating axis in
                # the first field
                continue
            
            constructs = [construct]
            for f in fields[1:]:
                c = f.constructs.get(key)
                if c is None:
                    # This field does not have this construct
                    constructs = None
                    break
                
                constructs.append(c)

            if not constructs:
                # Not every field has this construct, so remove it from the
                # output field.
                out.del_construct(key)
                continue
            
            # Still here? Then try concatenating the constructs from
            # each field.
            try:
                construct = construct.concatenate(constructs,
                                                  axis=construct_axes.index(dim),
                                                  _preserve=_preserve)
            except ValueError:
                # Couldn't concatenate this construct, so remove it from
                # the output field.
                out.del_construct(key)
            else:
                # Successfully concatenated this construct, so insert
                # it into the output field.
                out.set_construct(construct, key=key,
                                  axes=construct_axes, copy=False)
        #--- End: for

#        for role in ('d', 'a', 'm', 'f', 'c'):
#            for key, item in field0.items(role=role).items():
#                item_axes = field0.get_data_axes(key)
#
#                if dim not in item_axes:
#                    # This item does not span the concatenating axis in
#                    # the first field
#                    continue
#
#                items = [item]
#                for f in fields[1:]:
#                    i = f.item(key)
#                    if i is not None:
#                        items.append(i)                    
#                    else:
#                        # This field does not have this item
#                        items = None
#                        break
#                #--- End: for
#
#                if not items:
#                    # Not every field has this item, so remove it from the
#                    # output field.
#                    out.remove_item(key)
#                    continue
#                
#                # Still here? Then try concatenating the items from
#                # each field.
#                try:
#                    item = item.concatenate(items, axis=item_axes.index(dim),
#                                            _preserve=_preserve)
#                except ValueError:
#                    # Couldn't concatenate this item, so remove it from
#                    # the output field.
#                    out.remove_item(key)
#                else:
#                    # Successfully concatenated this item, so insert
#                    # it into the output field.
#                    out.insert_item(role, item, key=key, axes=item_axes,
#                                    copy=False, replace=True)
#            #--- End: for
#        #--- End: for

        return out


    def cyclic(self, identity=None, iscyclic=True, period=None,
               **kwargs):
        '''Set the cyclicity of an axis.

    .. versionadded:: 1.0
    
    .. seealso:: `autocyclic`, `domain_axis`, `iscyclic`, `period`
    
    :Parameters:
    
        identity:
           Select the domain axis construct by one of:
    
              * An identity or key of a 1-d coordinate construct that
                whose data spans the domain axis construct.
    
              * A domain axis construct identity or key.
    
              * The position of the domain axis construct in the field
                construct's data.
    
            The *identity* parameter selects the domain axis as
            returned by this call of the field's `domain_axis` method:
            ``f.domain_axis(identity)``.
    
        iscyclic: `bool`, optional
            If `False` then the axis is set to be non-cyclic. By default
            the selected axis is set to be cyclic.
    
        period: optional       
            The period for a dimension coordinate object which spans
            the selected axis. May be any numeric scalar object that
            can be converted to a `Data` object (which includes numpy
            array and `Data` objects). The absolute value of *period*
            is used. If *period* has units then they must be
            compatible with those of the dimension coordinates,
            otherwise it is assumed to have the same units as the
            dimension coordinates.
    
        axes: deprecated at version 3.0.0
            Use the *identity* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `set`
            The construct keys of the domain axes which were cyclic
            prior to the new setting, or the current cyclic domain
            axes if no axis was specified.
    
    **Examples:**
    
    >>> f.cyclic()
    set()
    >>> f.cyclic('X', period=360)
    set()
    >>> f.cyclic()
    {'domainaxis2'}
    >>> f.cyclic('X', iscyclic=False)
    {'domainaxis2'}
    >>> f.cyclic()
    set()

        '''    
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'cyclic', kwargs) # pragma: no cover

        data = self.get_data(None)
        if data is None:
            return set()

        data_axes = self.get_data_axes()
        old = set([data_axes[i] for i in data.cyclic()])

        if identity is None:            
            return old

        axis = self.domain_axis(identity, key=True)        
        
        try:
            data.cyclic(data_axes.index(axis), iscyclic)
        except ValueError:
            pass

        if iscyclic:
            dim = self.dimension_coordinate(axis, default=None)
            if dim is not None:
                if period is not None:
                    dim.period(period)
                elif dim.period() is None:
                    raise ValueError(
                        "A cyclic dimension coordinate must have a period")
        #--- End: if

        return old


    def weights(self, weights='auto', scale=False, components=False,
                methods=False, **kwargs):
        '''Return weights for the data array values.

    The weights are those used during a statistical collapse of the
    data. For example when computing a area weight average.
    
    Weights for any combination of axes may be returned.
    
    Weights are either derived from the field's metadata (such as
    coordinate cell sizes) or provided explicitly in the form of other
    `Field` objects. In any case, the outer product of these weights
    components is returned in a field which is broadcastable to the
    orginal field (see the *components* parameter for returning the
    components individually).
    
    By default null, equal weights are returned.
    
    .. versionadded:: 1.0
    
    .. seealso:: `cell_area`, `collapse`
    
    :Parameters:
    
    TODO
        weights: *optional*

            Specify the weights to be created. There are two distinct
            methods: **type 1** will always succeed in creating
            weights for all axes of the field, at the expense of not
            always being able to control exactly how the weights are
            created (see the *methods* parameter); **type 2** allows
            particular types of weights to be defined for particular
            axes and an exception will be raised if it is not possible
            to the create weights.
    
              * **Type 1**: *weights* may be one of:
            
                  ==========  ============================================
                  *weights*   Description
                  ==========  ============================================
                  `None`      Equal weights for all axes. This the
                              default.
    
                  ``'auto'``  Weights are created for non-overlapping
                              subsets of the axes by the methods
                              enumerated in the above notes. Set the
                              *methods* parameter to find out how the
                              weights were actually created.
    
                              In this case weights components are created
                              for all axes of the field by one or more of
                              the following methods, in order of
                              preference,
                            
                                1. Volume cell measures
                                2. Area cell measures
                                3. Area calculated from (grid) latitude
                                   and (grid) longitude dimension
                                   coordinates with bounds
                                4. Cell sizes of dimension coordinates
                                   with bounds
                                5. Equal weights
    
                              and the outer product of these weights
                              components is returned in a field which is
                              broadcastable to the orginal field (see the
                              *components* parameter).
                  ==========  ============================================
    
           ..
    
              * **Type 2**: *weights* may be one, or a sequence, of:
              
                  ============  ==========================================
                  *weights*     Description     
                  ============  ==========================================
                  ``'area'``    Cell area weights from the field's area
                                cell measure construct or, if one doesn't
                                exist, from (grid) latitude and (grid)
                                longitude dimension coordinates. Set the
                                *methods* parameter to find out how the
                                weights were actually created.
                  
                  ``'volume'``  Cell volume weights from the field's
                                volume cell measure construct.
                  
                  items         Weights from the cell sizes of the
                                dimension coordinate objects that would be
                                selected by this call of the field's
                                `~cf.Field.dims` method: ``f.dims(items,
                                **kwargs)``. See `cf.Field.dims` for
                                details. TODO
                  
                  `Field`       Take weights from the data array of
                                another field, which must be broadcastable
                                to this field.
                  ============  ==========================================
     
                If *weights* is a sequence of any combination of the
                above then the returned field contains the outer
                product of the weights defined by each element of the
                sequence. The ordering of the sequence is irrelevant.
    
                  *Parameter example:*
                    To create to 2-dimensional weights based on cell
                    areas: ``f.weights('area')``. To create to
                    3-dimensional weights based on cell areas and
                    linear height: ``f.weights(['area', 'Z'])``.
    
        scale: `bool`, optional
            If `True` then scale the returned weights so that they are
            less than or equal to 1.
    
        components: `bool`, optional
            If `True` then a dictionary of orthogonal weights components
            is returned instead of a field. Each key is a tuple of
            integers representing axes positions in the field's data
            array with corresponding values of weights in `Data`
            objects. The axes of weights match the axes of the field's
            data array in the order given by their dictionary keys.
    
        methods: `bool`, optional
            If `True`, then return a dictionary describing methods used
            to create the weights.
    
        kwargs: deprecated at version 3.0.0.
    
    :Returns:
    
        `Field` or `dict`
            The weights field or, if *components* is True, orthogonal
            weights in a dictionary.
    
    **Examples:**
    
    >>> f
    <CF Field: air_temperature(time(1800), latitude(145), longitude(192)) K>
    >>> f.weights()
    <CF Field: long_name:weight(time(1800), latitude(145), longitude(192)) 86400 s.rad>
    >>> f.weights('auto', scale=True)
    <CF Field: long_name:weight(time(1800), latitude(145), longitude(192)) 1>
    >>> f.weights('auto', components=True)
    {(0,): <CF Data(1800): [1.0, ..., 1.0] d>,
     (1,): <CF Data(145): [5.94949998503e-05, ..., 5.94949998503e-05]>,
     (2,): <CF Data(192): [0.0327249234749, ..., 0.0327249234749] radians>}
    >>> f.weights('auto', components=True, scale=True)
    {(0,): <CF Data(1800): [1.0, ..., 1.0]>,
     (1,): <CF Data(145): [0.00272710399807, ..., 0.00272710399807]>,
     (2,): <CF Data(192): [1.0, ..., 1.0]>}
    >>> f.weights('auto', methods=True)
    {(0,): 'linear time',
     (1,): 'linear sine latitude',
     (2,): 'linear longitude'}

        '''
#        def _field_of_weights(data, domain=None, axes=None):
        def _scalar_field_of_weights(data):
            '''Return a field of weights with long_name ``'weight'``.

    :Parameters:
    
        data: `Data`
            The weights which comprise the data array of the weights
            field.

    :Returns:

        `Field`

            '''
#            w = type(self)(data=data, copy=False)
            w = type(self)()
            w.set_data(data, copy=False)            
            w.long_name = 'weight'
            w.comment   = 'Weights for {!r}'.format(self)
            return w
        #--- End: def

        def _measure_weights(self, measure, comp, weights_axes, auto=False):
            '''Cell measure weights

    :Parameters:

    :Returns:

        `bool`

            '''
            m = self.cell_measures.filter_by_measure(measure)

            if not m:
                if measure == 'area':
                    return False
                if auto:
                    return
                
                raise ValueError(
                    "Can't get weights: No {!r} cell measure".format(measure))
            elif len(m) > 1:
                if auto:
                    return False
                
                raise ValueError("Found multiple 'area' cell measures")                

            key, clm = dict(m).popitem()    
            
            clm_axes0 = self.get_data_axes(key)
            
            clm_axes = tuple([axis for axis, n in zip(clm_axes0, clm.data.shape)
                              if n > 1])
                
            for axis in clm_axes:
                if axis in weights_axes:
                    if auto:
                        return False
                    raise ValueError(
                        "Multiple weights specifications for {!r} axis".format(
                            self.constructs.domain_axis_identity(axis)))
            #--- End: for
            
            clm = clm.get_data().copy()
            if clm_axes != clm_axes0:
                iaxes = [clm_axes0.index(axis) for axis in clm_axes]
                clm.squeeze(iaxes, inplace=True)
            
            if methods:
                comp[tuple(clm_axes)] = measure+' cell measure'
            else:    
                comp[tuple(clm_axes)] = clm
                
            weights_axes.update(clm_axes)
            
            return True
        #--- End: def
        
        def _linear_weights(self, axis, comp, weights_axes, auto=False):
            # ------------------------------------------------------------
            # 1-d linear weights from dimension coordinates
            # ------------------------------------------------------------
            da_key = self.domain_axis(axis, key=True, default=None)
            if da_key is None:
                if auto:
                    return
                
                raise ValueError("Can't create weights: Can't find axis matching {!r}".format(
                    axis))

            dim = self.dimension_coordinate(da_key, default=None)
            if dim is None:
                if auto:
                    return
                
                raise ValueError(
                    "Can't create weights: Can't find dimension coodinates matching {!r}".format(
                        axis))
            
            if dim.size == 1:
                return

            if da_key in weights_axes:
                if auto:
                    return
                
                raise ValueError(
                    "Can't create weights: Multiple weights specifications for {!r} axis".format(
                        axis))

            if not dim.has_bounds():
                if auto:
                    return
                
                raise ValueError(
                    "Can't create weights: Can't find linear weights for {!r} axis: No bounds".format(
                        axis))
            
            if dim.has_bounds():
                if methods:
                    comp[(da_key,)] = 'linear '+self.constructs.domain_axis_identity(da_key)
                else: 
                    comp[(da_key,)] = dim.cellsize
            #--- End: if

            weights_axes.add(da_key)
        #--- End: def
            
        def _area_weights_XY(self, comp, weights_axes, auto=False): 
            # ----------------------------------------------------
            # Calculate area weights from X and Y dimension
            # coordinates
            # ----------------------------------------------------
            xdims = dict(self.dimension_coordinates('X'))
            ydims = dict(self.dimension_coordinates('Y'))

            if not (xdims and ydims):
                if auto:
                    return
                
                raise ValueError(
                    "Insufficient coordinate constructs for calculating area weights")

            xkey, xcoord = xdims.popitem()
            ykey, ycoord = ydims.popitem()
                
            if xdims or ydims:
                if auto:
                    return
                
                raise ValueError(
                    "Ambiguous coordinate constructs for calculating area weights")

            if xcoord.Units.equivalent(Units('radians')) and ycoord.Units.equivalent(Units('radians')):
                pass
            elif xcoord.Units.equivalent(Units('metres')) and ycoord.Units.equivalent(Units('metres')):
                pass
            else:
                if auto:
                    return
                
                raise ValueError(
                    "Insufficient coordinate constructs for calculating area weights")

            xaxis = self.get_data_axes(xkey)[0]
            yaxis = self.get_data_axes(ykey)[0]
            
            for axis in (xaxis, yaxis):
                if axis in weights_axes:
                    if auto:
                        return
                    
                    raise ValueError(
                        "Multiple weights specifications for {!r} axis".format( 
                            self.constructs.domain_axis_identity(axis)))

            if xcoord.size > 1:
                if not xcoord.has_bounds(): 
                    if auto:
                        return
                    
                    raise ValueError(
                        "Can't create area weights: No bounds for {!r} axis".format(
                            xcoord.identity()))

                if methods:
                    comp[(xaxis,)] = 'linear ' + xcoord.identity()
                else:
                    cells = xcoord.cellsize
                    if xcoord.Units.equivalent(Units('radians')):
                        cells.Units = _units_radians
                    else:
                        cells.Units = Units('metres')
                        
                    comp[(xaxis,)] = cells

                weights_axes.add(xaxis)
            #--- End: if

            if ycoord.size > 1:
                if not ycoord.has_bounds():
                    if auto:
                        return
                    
                    raise ValueError(
                        "Can't create area weights: No bounds for {!r} axis".format(
                            ycoord.identity()))

                if ycoord.Units.equivalent(Units('radians')):
                    ycoord = ycoord.clip(-90, 90, units=Units('degrees'))
                    ycoord.sin(inplace=True)
    
                    if methods:
                        comp[(yaxis,)] = 'linear sine '+ycoord.identity()
                    else:            
                        comp[(yaxis,)] = ycoord.cellsize
                else:                    
                    if methods:
                        comp[(yaxis,)] = 'linear '+ycoord.identity()
                    else:            
                        comp[(yaxis,)] = ycoord.cellsize
                #--- End: if
                        
                weights_axes.add(yaxis)
            #--- End: if
        #--- End: def

        def _field_weights(self, fields, comp, weights_axes):
            # ------------------------------------------------------------
            # Field weights
            # ------------------------------------------------------------
            s = self.analyse_items()

            for w in fields:
                t = w.analyse_items()
    
                if t['undefined_axes']:
#                    if t.axes(size=gt(1)).intersection(t['undefined_axes']):
                    if set(t.domain_axes.filter_by_size(gt(1))).intersection(t['undefined_axes']):
                        raise ValueError("345jn456jn TODO")
    
                w = w.squeeze()

                axis1_to_axis0 = {}

                for axis1 in w.get_data_axes():
                    identity = t['axis_to_id'].get(axis1, None)
                    if identity is None:
                        raise ValueError(
                            "Weights field has unmatched, size > 1 {!r} axis".format(
                                w.constructs.domain_axis_identity(axis1)))
                    
                    axis0 = s['id_to_axis'].get(identity, None)
                    if axis0 is None:
                        raise ValueError(
                            "Weights field has unmatched, size > 1 {!r} axis".format(
                                identity))

                    w_axis_size = w.domain_axes[axis1].get_size()
                    self_axis_size = self.domain_axes[axis0].get_size()
#                    if w.domain_axes[axis1].get_size() != self.axis_size(axis0):
                    if w_axis_size != self_axis_size:
                        raise ValueError(
                            "Weights field has incorrectly sized {!r} axis ({} != {})".format(
                                identity, w_axis_size, self_axis_size))
    
                    axis1_to_axis0[axis1] = axis0                    

                    # Check that the defining coordinate data arrays are
                    # compatible
                    key0 = s['axis_to_coord'][axis0]                
                    key1 = t['axis_to_coord'][axis1]
   
                    if not self._equivalent_construct_data(w, key0=key0, key1=key1, s=s, t=t):
                        raise ValueError(
                            "Weights field has incompatible {!r} coordinates".format(identity))
    
                    # Still here? Then the defining coordinates have
                    # equivalent data arrays
    
                    # If the defining coordinates are attached to
                    # coordinate references then check that those
                    # coordinate references are equivalent                    
                    refs0 = [key for key, ref in self.coordinate_references.item()
                             if key0 in ref.coordinates()]
                    refs1 = [key for key, ref in w.coordinate_references.items()
                             if key1 in ref.coordinates()]

                    nrefs = len(refs0)
                    if nrefs > 1 or nrefs != len(refs1):
                        # The defining coordinate are associated with
                        # different numbers of coordinate references
                        equivalent_refs = False
                    elif not nrefs:
                        # Neither defining coordinate is associated with a
                        # coordinate reference                    
                        equivalent_refs = True
                    else:  
                        # Each defining coordinate is associated with
                        # exactly one coordinate reference
                        equivalent_refs = self._equivalent_coordinate_references(
                            w,
                            key0=refs0[0], key1e=refs1[0],
                            s=s,t=t)

                    if not equivalent_refs:
                        raise ValueError(
                            "Input weights field has an incompatible coordinate reference")
                #--- End: for
    
                axes0 = tuple([axis1_to_axis0[axis1] for axis1 in w.get_data_axes()])
            
                for axis0 in axes0:
                    if axis0 in weights_axes:
                        raise ValueError(
                            "Multiple weights specified for {!r} axis".format(
                                self.constructs.domain_axis_identity(axis0)))
                #--- End: for
    
                comp[axes] = w.data
            
                weights_axes.update(axes)
        #--- End: def

        if weights is None:
            # --------------------------------------------------------
            # All equal weights
            # --------------------------------------------------------
            if components:
                # Return an empty components dictionary
                return {}
            
            # Return a field containing a single weight of 1
            return _scalar_field_of_weights(Data(1.0, '1'))

        # Still here?
        if methods:
            components = True

        comp         = {}
        data_axes    = self.get_data_axes()

        # All axes which have weights
        weights_axes = set()

        if isinstance(weights, str) and weights == 'auto':
            # --------------------------------------------------------
            # Auto-detect all weights
            # --------------------------------------------------------
            # Volume weights
            _measure_weights(self, 'volume', comp, weights_axes, auto=True)

            # Area weights
            if not _measure_weights(self, 'area', comp, weights_axes, auto=True):
                _area_weights_XY(self, comp, weights_axes, auto=True)

            # 1-d linear weights from dimension coordinates
#            for axis in self.dims():
            for dc_key in self.dimension_coordinates:
                axis = self.get_data_axes(dc_key)[0]
                _linear_weights(self, axis, comp, weights_axes, auto=True)
 
        elif isinstance(weights, dict):
            # --------------------------------------------------------
            # Dictionary
            # --------------------------------------------------------
            for key, value in weights.items():                
                try:
                    key = [data_axes[iaxis] for iaxis in key]
                except IndexError:
                    raise ValueError("TODO s ^^^^^^ csdcvd 3456 4")

                multiple_weights = weights_axes.intersection(key)
                if multiple_weights:
                    raise ValueError(
                        "Multiple weights specifications for {0!r} axis".format(
                            self.constructs.domain_axis_identity(multiple_weights.pop())))
                #--- End: if
                
                weights_axes.update(key)

                comp[tuple(key)] = value.copy()
        else:
            # --------------------------------------------------------
            # String or sequence
            # --------------------------------------------------------
            fields = []
            axes   = []
            cell_measures = []
            
            if isinstance(weights, str):
                if weights in ('area', 'volume'):
                    cell_measures = (weights,)
                else:
                    axes.append(weights)
            else:
                for w in tuple(weights):
                    if isinstance(w, self.__class__):
                        fields.append(w)
                    elif w in ('area', 'volume'):
                        cell_measures.append(w)
                    else:
                        axes.append(w)
            #--- End: if

            da_key_x = None
            da_key_y = None
            xaxis = self.domain_axis('X', key=True, default=None)
            yaxis = self.domain_axis('Y', key=True, default=None)
            for axis in axes:
                da_key = self.domain_axis(axis, key=True, default=None)
                da_key = self.domain_axis(axis, key=True, default=None)
                if da_key == xaxis:
                    da_key_x = da_key
                elif da_key == yaxis:
                    da_key_y = da_key
                
            if da_key_x and da_key_y:
                xdim = self.dimension_coordinate(xaxis, default=None)
                ydim = self.dimension_coordinate(yaxis, default=None)
                if (xdim is not None and ydim is not None and
                    xdim.has_bounds() and ydim.has_bounds() and
                    xdim.Units.equivalent(Units('radians')) and
                    ydim.Units.equivalent(Units('radians'))):
                    ydim = ydim.clip(-90, 90, units=Units('degrees'))
                    ydim.sin(inplace=True)
                    comp[(yaxis,)] = ydim.cellsize
            #--- End: if
            
            # Field weights
            _field_weights(self, fields, comp, weights_axes)

            # Volume weights
            if 'volume' in cell_measures:
                _measure_weights(self, 'volume', comp, weights_axes)
            
            # Area weights
            if 'area' in cell_measures:
                if not _measure_weights(self, 'area', comp, weights_axes):
                    _area_weights_XY(self, comp, weights_axes)      

            # 1-d linear weights from dimension coordinates
            for axis in axes:
                _linear_weights(self, axis, comp, weights_axes, auto=False)

            # Check for area weights specified by X and Y axes
            # separately and replace them with area weights
            xaxis = self.domain_axis('X', key=True, default=None)
            yaxis = self.domain_axis('Y', key=True, default=None)
            if (xaxis,) in comp and (yaxis,) in comp:
                del comp[(xaxis,)]
                del comp[(yaxis,)]
                weights_axes.discard(xaxis)
                weights_axes.discard(yaxis)
                if not _measure_weights(self, 'area', comp, weights_axes):
                    _area_weights_XY(self, comp, weights_axes)      
        #--- End: if
 
        # ------------------------------------------------------------
        # Scale the weights so that they are <= 1.0
        # ------------------------------------------------------------
        if scale and not methods:
            # What to do about -ve weights? dch
            for key, w in comp.items(): 
                wmax = w.data.max()    
                if wmax > 0:
                    wmax.dtype = float
                    if not numpy_can_cast(wmax.dtype, w.dtype):
                        w = w / wmax
                    else:
                        w /= wmax
                    comp[key] = w
        #--- End: if

        if components:
            # --------------------------------------------------------
            # Return a dictionary of component weights, which may be
            # empty.
            # -------------------------------------------------------- 
            components = {}
            for key, v in comp.items():
                key = [data_axes.index(axis) for axis in key]
                if not key:
                    continue

                components[tuple(key)] = v

            return components

        if methods:
            return components

        if not comp:
            # --------------------------------------------------------
            # No component weights have been defined so return an
            # equal weights field
            # --------------------------------------------------------
            return _scalar_field_of_weights(Data(1.0, '1'))
        
        # ------------------------------------------------------------
        # Return a weights field which is the outer product of the
        # component weights
        # ------------------------------------------------------------
        pp = sorted(comp.items())       
        waxes, wdata = pp.pop(0)
        while pp:
            a, y = pp.pop(0)
            wdata.outerproduct(y, inplace=True)
            waxes += a
        
        field = self.copy()
        field.del_data()
        field.del_data_axes()

        not_needed_axes = set(field.domain_axes).difference(weights_axes)

        for key in self.cell_methods:            
            field.del_construct(key)
            
        for key in field.coordinate_references:
            if field.coordinate_reference_domain_axes(key).intersection(not_needed_axes):
                field.del_coordinate_reference(key)
        #--- End: for
        
        for key in field.constructs.filter_by_axis('or', *not_needed_axes):
            field.del_construct(key)

        for key in not_needed_axes:
            field.del_construct(key)

        field.set_data(wdata, axes=waxes, copy=False)
        field.clear_properties()
        field.long_name = 'weights'

        return field


    def del_construct(self, identity, default=ValueError()):
        '''Remove a metadata construct.

    If a domain axis construct is selected for removal then it can't
    be spanned by any metdata construct data, nor the field
    construct's data; nor be referenced by any cell method constructs.
    
    However, a domain ancillary construct may be removed even if it is
    referenced by coordinate reference construct. In this case the
    reference is replace with `None`.
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `constructs`, `get_construct`, `has_construct`,
                 `set_construct`
    
    :Parameters:
    
        identity:
            Select the construct to removed. Must be
    
              * The identity or key of a metadata construct.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); a `Query` object
            (e.g. ``cf.eq('longitude')``); or a compiled regular
            expression (e.g. ``re.compile('^atmosphere')``) that
            selects the relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
            
            *Parameter example:*
              ``identity='measure:area'``
    
            *Parameter example:*
              ``identity='cell_area'``
    
            *Parameter example:*
              ``identity='long_name=Cell Area'``
    
            *Parameter example:*
              ``identity='cellmeasure1'``
    
        default: optional
            Return the value of the *default* parameter if the
            construct can not be removed, or does not exist. If set to
            an `Exception` instance then it will be raised instead.
    
    :Returns:
    
            The removed metadata construct.
    
    **Examples:**
    
    >>> f.del_construct('X')
    <CF DimensionCoordinate: grid_latitude(111) degrees>

        '''
        key = self.construct_key(identity, default=None)
        if key is None:
            return self._default(
                default,
                "Can't identify construct to delete from identity {!r}".format(identity))

        return super().del_construct(key, default=default)

            
    def del_coordinate_reference(self, identity, default=ValueError()):
        '''Remove a coordinate reference construct and all of its domain
    ancillary constructs.
            
    .. versionadded:: 3.0.0
    
    .. seealso:: `del_construct`
    
    :Parameters:
    
        identity:
            Select the coordinate reference construct by one of:
    
              * The identity or key of a coordinate reference
                construct.
    
            A construct identity is specified by a string
            (e.g. ``'grid_mapping_name:latitude_longitude'``,
            ``'latitude_longitude'``, ``'ncvar%lat_lon'``, etc.); a
            `Query` object (e.g. ``cf.eq('latitude_longitude')``); or
            a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            two identites:
    
               >>> x.identities()
               ['grid_mapping_name:latitude_longitude', 'ncvar%lat_lon']
    
            A identity's prefix of ``'grid_mapping_name:'`` or
            ``'standard_name:'`` may be omitted
            (e.g. ``'standard_name:atmosphere_hybrid_height_coordinate'``
            and ``'atmosphere_hybrid_height_coordinate'`` are both
            acceptable identities).
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'coordinatereference2'`` and
            ``'key%coordinatereference2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='standard_name:atmosphere_hybrid_height_coordinate'``
    
            *Parameter example:*
              ``identity='grid_mapping_name:rotated_latitude_longitude'``
    
            *Parameter example:*
              ``identity='transverse_mercator'``
    
            *Parameter example:*
              ``identity='coordinatereference1'``
    
            *Parameter example:*
              ``identity='key%coordinatereference1'``
    
            *Parameter example:*
              ``identity='ncvar%lat_lon'``
    
        default: optional
            Return the value of the *default* parameter if the
            construct can not be removed, or does not exist. If set to
            an `Exception` instance then it will be raised instead.
    
    :Returns:
    
            The removed coordinate reference construct.
    
    **Examples:**
    
    >>> f.del_coordinate_reference('rotated_latitude_longitude')
    <CF CoordinateReference: rotated_latitude_longitude>

        '''
        key = self.coordinate_reference(identity, key=True, default=None)
        if key is None:
            return self._default(
                default,
                "Can't identify construct to delete from identity {!r}".format(identity))

        ref = self.del_construct(key)
        
        for da_key in ref.coordinate_conversion.domain_ancillaries().values():
            self.del_construct(da_key, default=None)
            
        return ref


    def set_coordinate_reference(self, coordinate_reference, key=None,
                                 field=None, strict=True):
        '''Set a coordinate reference construct.

    By default, this is equivalent to using the `set_construct`
    method. If, however, the *field* parameter has been set then it is
    assumed to be a field construct that contains the new coordinate
    reference construct. In this case, existing coordinate and domain
    ancillary constructs will be referenced by the inserted coordinate
    reference construct, based on those which are referenced from the
    other parent field construct (given by the *field* parameter).

    .. versionadded:: 3.0.0
    
    .. seealso:: `set_construct`
    
    :Parameters:
    
        coordinate_reference: `CoordinateReference`
            The coordinate reference construct to be inserted.
    
        key: `str`, optional
            The construct identifier to be used for the construct. If
            not set then a new, unique identifier is created
            automatically. If the identifier already exisits then the
            exisiting construct will be replaced.
    
            *Parameter example:*
              ``key='coordinatereference1'``

        field: `Field`, optional
            A parent field construct that contains the new coordinate
            refence construct.

        strict: `bool`, optional
            If `False` then allow non-strict identities for
            identifying coordinate and domain ancillary metadata
            constructs.

    :Returns:
    
        `str`
            The construct identifier for the coordinate refernece
            construct.
    
        '''
        if field is None:
            return self.set_construct(coordinate_reference, key=key, copy=True)

        # Still here?
        ref = coordinate_reference.copy()

        ckeys = []
        for value in coordinate_reference.coordinates():
            if value in field.coordinates:
                identity = field.coordinates[value].identity(strict=strict)
                ckeys.append(self.coordinate(identity, key=True, default=None))
        #--- End: for
                
        ref.clear_coordinates()
        ref.set_coordinates(ckeys)

        coordinate_conversion = coordinate_reference.coordinate_conversion

        dakeys = {}
        for term, value in coordinate_conversion.domain_ancillaries().items():
            if value in field.domain_ancillaries:
                identity = field.domain_ancillaries[value].identity(strict=strict)
                dakeys[term] = self.domain_ancillary(identity, key=True, default=None)
            else:
                dakeys[term] = None
        #--- End: for

        ref.coordinate_conversion.clear_domain_ancillaries()
        ref.coordinate_conversion.set_domain_ancillaries(dakeys)

        return self.set_construct(ref, key=key, copy=False)
    #--- End: def

    
    def collapse(self, method, axes=None, squeeze=False, mtol=1,
                 weights=None, ddof=1, a=None, inplace=False,
                 group=None, regroup=False, within_days=None,
                 within_years=None, over_days=None, over_years=None,
                 coordinate='mid_range', group_by='coords',
                 group_span=None, group_contiguous=None,
                 verbose=False, _create_zero_size_cell_bounds=False,
                 _update_cell_methods=True, i=False, _debug=False,
                 **kwargs):
        r'''

    Collapse axes of the field.
    
    Collapsing one or more dimensions reduces their size and replaces
    the data along those axes with representative statistical
    values. The result is a new field construct with consistent
    metadata for the collapsed values.
    
    Collapsing an axis involves reducing its size with a given
    (typically statistical) method.
    
    By default all axes with size greater than 1 are collapsed
    completely (i.e. to size 1) with a given collapse method.

    *Example:*
      Find the minimum of the entire data:

      >>> b = a.collapse('minimum')

    The collapse can be applied to only a subset of the field
    construct's dimensions. In this case, the domain axis and
    coordinate constructs for the non-collapsed dimensions remain the
    same. This is implemented either with the axes keyword, or with a
    CF-netCDF cell methods-like syntax for describing both the
    collapse dimensions and the collapse method in a single
    string. The latter syntax uses construct identities instead of
    netCDF dimension names to identify the collapse axes.
    
    Statistics may be created to represent variation over one
    dimension or a combination of dimensions.

    *Example:*
       Two equivalent techniques for creating a field construct of
       temporal maxima at each horizontal location:

       >>> b = a.collapse('maximum', axes='T')
       >>> b = a.collapse('T: maximum')

    *Example:*
      Find the horizontal maximum, with two equivalent techniques.

      >>> b = a.collapse('maximum', axes=['X', 'Y'])
      >>> b = a.collapse('X: Y: maximum')

    Variation over horizontal area may also be specified by the
    special identity 'area'. This may be used for any horizontal
    coordinate reference system.

    *Example:*
      Find the horizontal maximum using the special identity 'area':

      >>> b=a.collapse('area: maximum')

    
    **Collapse methods**
    
    The following collapse methods are available, over any subset of
    the domain axes:
    
    ========================  =====================================================
    Method                    Description
    ========================  =====================================================
    ``'maximum'``             The maximum of the values.
                              
    ``'minimum'``             The minimum of the values.
                                       
    ``'sum'``                 The sum of the values.
                              
    ``'mid_range'``           The average of the maximum and the minimum of the
                              values.
                              
    ``'range'``               The absolute difference between the maximum and
                              the minimum of the values.
                              
    ``'mean'``                The unweighted mean of :math:`N` values
                              :math:`x_i` is
                              
                              .. math:: \mu=\frac{1}{N}\sum_{i=1}^{N} x_i
                              
                              The :ref:`weighted <Weights>` mean of
                              :math:`N` values :math:`x_i` with
                              corresponding weights :math:`w_i` is
    
                              .. math:: \hat{\mu}=\frac{1}{V_{1}}
                                                    \sum_{i=1}^{N} w_i
                                                    x_i
    
                              where :math:`V_{1}=\sum_{i=1}^{N} w_i`, the
                              sum of the weights.
                                   
    ``'variance'``            The unweighted variance of :math:`N` values
                              :math:`x_i` and with :math:`N-ddof` degrees
                              of freedom (:math:`ddof\ge0`) is
    
                              .. math:: s_{N-ddof}^{2}=\frac{1}{N-ddof}
                                          \sum_{i=1}^{N} (x_i - \mu)^2
    
                              The unweighted biased estimate of the
                              variance (:math:`s_{N}^{2}`) is given by
                              :math:`ddof=0` and the unweighted unbiased
                              estimate of the variance using Bessel's
                              correction (:math:`s^{2}=s_{N-1}^{2}`) is
                              given by :math:`ddof=1`.
    
                              The :ref:`weighted <Weights>` biased
                              estimate of the variance of :math:`N` values
                              :math:`x_i` with corresponding weights
                              :math:`w_i` is
    
                              .. math:: \hat{s}_{N}^{2}=\frac{1}{V_{1}}
                                                        \sum_{i=1}^{N}
                                                        w_i(x_i -
                                                        \hat{\mu})^{2}
                                   
                              The corresponding :ref:`weighted <Weights>`
                              unbiased estimate of the variance is
                              
                              .. math:: \hat{s}^{2}=\frac{1}{V_{1} -
                                                    (V_{1}/V_{2})}
                                                    \sum_{i=1}^{N}
                                                    w_i(x_i -
                                                    \hat{\mu})^{2}
    
                              where :math:`V_{2}=\sum_{i=1}^{N} w_i^{2}`,
                              the sum of the squares of weights. In both
                              cases, the weights are assumed to be
                              non-random reliability weights, as
                              opposed to frequency weights.
                                  
    ``'standard_deviation'``  The variance is the square root of the variance.
    
    ``'sample_size'``         The sample size, :math:`N`, as would be used for 
                              other statistical calculations.
                              
    ``'sum_of_weights'``      The sum of weights, :math:`V_{1}`, as would be
                              used for other statistical calculations.
    
    ``'sum_of_weights2'``     The sum of squares of weights, :math:`V_{2}`, as
                              would be used for other statistical calculations.
    ========================  =====================================================
    

    **Data type and missing data**
    
    In all collapses, missing data array elements are accounted for in
    the calculation.
    
    Any collapse method that involves a calculation (such as
    calculating a mean), as opposed to just selecting a value (such as
    finding a maximum), will return a field containing double
    precision floating point numbers. If this is not desired then the
    data type can be reset after the collapse with the `dtype`
    attribute of the field construct.
    

    **Collapse weights**
    
    The calculations of means, standard deviations and variances are,
    by default, **not weighted**. For weights to be incorporated in
    the collapse, the axes to be weighted must be identified with the
    *weights* keyword.
    
    Weights are either derived from the field construct's metadata
    (such as cell sizes), or may be provided explicitly in the form of
    other field constructs containing data of weights values. In
    either case, the weights actually used are those derived by the
    `weights` method of the field construct with the same weights
    keyword value. Collapsed axes that are not identified by the
    *weights* keyword are un-weighted during the collapse operation.
    
    *Example:*
      Create a weighted time average:

      >>> b = a.collapse('T: mean', weights='T')

    *Example:*
      Calculate the mean over the time and latitude axes, with
      weights only applied to the latitude axis:

      >>> b = a.collapse('T: Y: mean', weights='Y')

    *Example*
      Alternative syntax for specifying area weights:

      >>> b = a.collapse('area: mean', weights='area')


    **Multiple collapses**
    
    Multiple collapses normally require multiple calls to `collapse`:
    one on the original field construct and then one on each interim
    field construct.

    *Example:*
      Calculate the temporal maximum of the weighted areal means
      using two independent calls: 
      
      >>> b = a.collapse('area: mean', weights='area').collapse('T: maximum')

    If preferred, multiple collapses may be carried out in a single
    call by using the CF-netCDF cell methods-like syntax (note that
    the colon (:) is only used after the construct identity that
    specifies each axis, and a space delimits the separate collapses).
    
    *Example:*
      Calculate the temporal maximum of the weighted areal means in
      a single call, using the cf-netCDF cell methods-like syntax:
      
      >>> b =a.collapse('area: mean T: maximum', weights='area')


    **Grouped collapses**
    
    A grouped collapse is one for which as axis is not collapsed
    completely to size 1. Instead the collapse axis is partitioned
    into groups and each group is collapsed to size 1. The resulting
    axis will generally have more than one element. For example,
    creating 12 annual means from a timeseries of 120 months would be
    a grouped collapse.
    
    The *group* keyword defines the size of the groups. Groups can be
    defined in a variety of ways, including with `Query`,
    `TimeDuration` and `Data` instances.
    
    Not every element of the collapse axis needs to be in
    group. Elements that are not selected by the *group* keyword are
    excluded from the result.

    *Example:*
      Create annual maxima from a time series, defining a year to
      start on 1st December.

      >>> b = a.collapse('T: maximum', group=cf.Y(month=12))

    *Example:*
      Find the maximum of each group of 6 elements along an axis.
	     
      >>> b = a.collapse('T: maximum', group=6)

    *Example:*
      Create December, January, February maxima from a time series.

      >>> b = a.collapse('T: maximum', group=cf.djf())

    *Example:*
      Create maxima for each 3-month season of a timeseries (DJF, MAM,
      JJA, SON).

      >>> b = a.collapse('T: maximum', group=cf.seasons())

    *Example:*
      Calculate zonal means for the western and eastern hemispheres.
	     
      >>> b = a.collapse('X: mean', group=cf.Data(180, 'degrees'))
    
    Groups can be further described with the *group_span* (to ignore
    groups whose actual span is less than a given value) and
    *group_contiguous* (to ignore non-contiguous groups, or any
    contiguous group containing overlapping cells).
       

    **Climatological statistics**
    
    Climatological statistics may be derived from corresponding
    portions of the annual cycle in a set of years (e.g. the average
    January temperatures in the climatology of 1961-1990, where the
    values are derived by averaging the 30 Januarys from the separate
    years); or from corresponding portions of the diurnal cycle in a
    set of days (e.g. the average temperatures for each hour in the
    day for May 1997). A diurnal climatology may also be combined with
    a multiannual climatology (e.g. the minimum temperature for each
    hour of the average day in May from a 1961-1990 climatology).
    
    Calculation requires two or three collapses, depending on the
    quantity being created, all of which are grouped collapses. Each
    collapse method needs to indicate its climatological nature with
    one of the following qualifiers,
    
    ================  =======================
    Method qualifier  Associated keyword
    ================  =======================
    ``within years``  *within_years*
    ``within days``   *within_days*
    ``over years``    *over_years* (optional)
    ``over days``     *over_days* (optional)
    ================  =======================
    
    and the associated keyword specifies how the method is to be
    applied.

    *Example*
      Calculate the multiannual average of the seasonal means:
       
      >>> b = a.collapse('T: mean within years T: mean over years',
      ...                within_years=cf.seasons(), weights='T')

    *Example:*
      Calculate the multiannual variance of the seasonal
      minima. Note that the units of the result have been changed
      from 'K' to 'K2':

      >>> b = a.collapse('T: minimum within years T: variance over years',
      ...                within_years=cf.seasons(), weights='T')

    When collapsing over years, it is assumed by default that the each
    portion of the annual cycle is collapsed over all years that are
    present. This is the case in the above two examples. It is
    possible, however, to restrict the years to be included, or group
    them into chunks, with the *over_years* keyword.

    *Example:*
      Calculate the multiannual average of the seasonal means in 5
      year chunks:

      >>> b = a.collapse('T: mean within years T: mean over years', weights='T',
      ...                within_years=cf.seasons(), over_years=cf.Y(5))

    *Example:*
      Calculate the multiannual average of the seasonal means,
      restricting the years from 1963 to 1968:

      >>> b = a.collapse('T: mean within years T: mean over years', weights='T',
      ...                within_years=cf.seasons(),
      ...                over_years=cf.year(cf.wi(1963, 1968)))

    Similarly for collapses over days, it is assumed by default that
    the each portion of the diurnal cycle is collapsed over all days
    that are present, But it is possible to restrict the days to be
    included, or group them into chunks, with the *over_days* keyword.
    
    The calculation can be done with multiple collapse calls, which
    can be useful if the interim stages are needed independently, but
    be aware that the interim field constructs will have
    non-CF-compliant cell method constructs.

    *Example:*
      Calculate the multiannual maximum of the seasonal standard
      deviations with two separate collapse calls:

      >>> b = a.collapse('T: standard_deviation within years',
      ...                within_years=cf.seasons(), weights='T')


    .. versionadded:: 1.0
    
    .. seealso:: `weights`, `weights`, `max`, `mean`, `mid_range`,
                 `min`, `range`, `sample_size`, `sd`, `sum`, `var`
    
    :Parameters:
    
        method: `str`
            Define the collapse method. All of the axes specified by
            the *axes* parameter are collapsed simultaneously by this
            method. The method is given by one of the following
            strings:
    
              ========================================  =========================
              *method*                                  Description
              ========================================  =========================
              ``'max'`` or ``'maximum'``                Maximum                  
              ``'min'`` or ``'minimum'``                Minimum                      
              ``'sum'``                                 Sum                      
              ``'mid_range'``                           Mid-range                
              ``'range'``                               Range                    
              ``'mean'`` or ``'average'`` or ``'avg'``  Mean                         
              ``'var'`` or ``'variance'``               Variance                 
              ``'sd'`` or ``'standard_deviation'``      Standard deviation       
              ``'sample_size'``                         Sample size                      
              ``'sum_of_weights'``                      Sum of weights           
              ``'sum_of_weights2'``                     Sum of squares of weights
              ========================================  =========================
    
            An alternative form is to provide a CF cell methods-like
            string. In this case an ordered sequence of collapses may
            be defined and both the collapse methods and their axes
            are provided. The axes are interpreted as for the *axes*
            parameter, which must not also be set. For example:
              
            >>> g = f.collapse('time: max (interval 1 hr) X: Y: mean dim3: sd')
            
            is equivalent to:
            
            >>> g = f.collapse('max', axes='time')
            >>> g = g.collapse('mean', axes=['X', 'Y'])
            >>> g = g.collapse('sd', axes='dim3')    
    
            Climatological collapses are carried out if a *method*
            string contains any of the modifiers ``'within days'``,
            ``'within years'``, ``'over days'`` or ``'over
            years'``. For example, to collapse a time axis into
            multiannual means of calendar monthly minima:
    
            >>> g = f.collapse('time: minimum within years T: mean over years',
            ...                 within_years=cf.M())
              
            which is equivalent to:
              
            >>> g = f.collapse('time: minimum within years', within_years=cf.M())
            >>> g = g.collapse('mean over years', axes='T')
    
        axes: (sequence of) `str`, optional
            The axes to be collapsed, defined by those which would be
            selected by passing each given axis description to a call
            of the field's `domain_axis` method. For example, for a
            value of ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected. If a selected axis
            has size 1 then it is ignored. By default all axes with
            size greater than 1 are collapsed.
   
            *Parameter example:*
              ``axes='X'``
    
            *Parameter example:*
              ``axes=['X']``
    
            *Parameter example:*
              ``axes=['X', 'Y']``
    
            *Parameter example:*
              ``axes=['Z', 'time']``
    
            If the *axes* parameter has the special value ``'area'``
            then it is assumed that the X and Y axes are intended.
    
            *Parameter example:*
              ``axes='area'`` is equivalent to ``axes=['X', 'Y']``.
    
            *Parameter example:*
              ``axes=['area', Z']`` is equivalent to ``axes=['X', 'Y',
              'Z']``.
    
        weights: optional
            Specify the weights for the collapse. **By default the
            collapse is unweighted**. The weights are those that would
            be returned by this call of the field's
            `~cf.Field.weights` method: ``f.weights(weights,
            components=True)``. See `cf.Field.weights` for details.
            By default *weights* is `None` (``f.weights(None,
            components=True)`` creates equal weights for all
            elements).
    
            *Parameter example:*
              To specify weights based on cell areas use
              ``weights='area'``.
    
            *Parameter example:*
              To specify weights based on cell areas and linearly in
              time you could set ``weights=('area', 'T')``.
    
            *Parameter example:*
              To automatically detect the best weights available for
              all axes from the metadata: ``weights='auto'``. See
              `cf.Field.weights` for details on how the weights are
              derived in this case.
    
        squeeze: `bool`, optional
            If `True` then size 1 collapsed axes are removed from the
            output data array. By default the axes which are collapsed
            are retained in the result's data array.
    
        mtol: number, optional        
            Set the fraction of input array elements which is allowed
            to contain missing data when contributing to an individual
            output array element. Where this fraction exceeds *mtol*,
            missing data is returned. The default is 1, meaning that a
            missing datum in the output array only occurs when its
            contributing input array elements are all missing data. A
            value of 0 means that a missing datum in the output array
            occurs whenever any of its contributing input array
            elements are missing data. Any intermediate value is
            permitted.
    
            *Parameter example:*
              To ensure that an output array element is a missing
              datum if more than 25% of its input array elements are
              missing data: ``mtol=0.25``.
    
        ddof: number, optional
            The delta degrees of freedom in the calculation of a
            standard deviation or variance. The number of degrees of
            freedom used in the calculation is (N-*ddof*) where N
            represents the number of non-missing elements. By default
            *ddof* is 1, meaning the standard deviation and variance
            of the population is estimated according to the usual
            formula with (N-1) in the denominator to avoid the bias
            caused by the use of the sample mean (Bessel's
            correction).
    
        coordinate: `str`, optional
            Set how the cell coordinate values for collapsed axes are
            defined. This has no effect on the cell bounds for the
            collapsed axes, which always represent the extrema of the
            input coordinates. Valid values are:
    
              ===============  ===========================================
              *coordinate*     Description
              ===============  ===========================================        
              ``'mid_range'``  An output coordinate is the average of the
                               first and last input coordinate bounds (or
                               the first and last coordinates if there are
                               no bounds). This is the default.
                               
              ``'min'``        An output coordinate is the minimum of the
                               input coordinates.
                               
              ``'max'``        An output coordinate is the maximum of the
                               input coordinates.
              ===============  ===========================================
           
        group: optional
            Independently collapse groups of axis elements. Upon
            output, the results of the collapses are concatenated so
            that the output axis has a size equal to the number of
            groups. The *group* parameter defines how the elements are
            partitioned into groups, and may be one of:
    
              * A `Data` object defining the group size in terms of
                ranges of coordinate values. The first group starts at
                the first coordinate bound of the first axis element
                (or its coordinate if there are no bounds) and spans
                the defined group size. Each susbsequent group
                immediately follows the preceeeding one. By default
                each group contains the consective run of elements
                whose coordinate values lie within the group limits
                (see the *group_by* parameter).
    
                  *Parameter example:*
                    To define groups of 10 kilometres:
                    ``group=cf.Data(10, 'km')``.
    
                  *Note:*
                    * By default each element will be in exactly one group
                      (see the *group_by*, *group_span* and
                      *group_contiguous* parameters).
                    * By default groups may contain different numbers of
                      elements.
                    * If no units are specified then the units of the
                      coordinates are assumed.
    
            ..
    
              * A `TimeDuration` object defining the group size in
                terms of calendar months and years or other time
                intervals. The first group starts at or before the
                first coordinate bound of the first axis element (or
                its coordinate if there are no bounds) and spans the
                defined group size. Each susbsequent group immediately
                follows the preceeeding one. By default each group
                contains the consective run of elements whose
                coordinate values lie within the group limits (see the
                *group_by* parameter).
    
                  *Parameter example:*
                    To define groups of 5 days, starting and ending at
                    midnight on each day: ``group=cf.D(5)`` (see
                    `cf.D`).
    
                  *Parameter example:*
                    To define groups of 1 calendar month, starting and
                    ending at day 16 of each month:
                    ``group=cf.M(day=16)`` (see `cf.M`).
    
                  *Note:*
                    * By default each element will be in exactly one group
                      (see the *group_by*, *group_span* and
                      *group_contiguous* parameters).
                    * By default groups may contain different numbers of
                      elements.
                    * The start of the first group may be before the first
                      first axis element, depending on the offset defined
                      by the time duration. For example, if
                      ``group=cf.Y(month=12)`` then the first group will
                      start on the closest 1st December to the first axis
                      element.
    
            ..
    
              * A (sequence of) `Query`, each of which is a
                condition defining one or more groups. Each query
                selects elements whose coordinates satisfy its
                condition and from these elements multiple groups are
                created - one for each maximally consecutive run
                within these elements.
    
                  *Parameter example:*
                    To define groups of the season MAM in each year:
                    ``group=cf.mam()`` (see `cf.mam`).
                  
                  *Parameter example:*
                    To define groups of the seasons DJF and JJA in
                    each year: ``group=[cf.jja(), cf.djf()]``. To
                    define groups for seasons DJF, MAM, JJA and SON in
                    each year: ``group=cf.seasons()`` (see `cf.djf`,
                    `cf.jja` and `cf.season`).
                  
                  *Parameter example:*
                    To define groups for longitude elements less than
                    or equal to 90 degrees and greater than 90
                    degrees: ``group=[cf.le(90, 'degrees'), cf.gt(90,
                    'degrees')]`` (see `cf.le` and `cf.gt`).
    
                  *Note:*
                    * If a coordinate does not satisfy any of the
                      conditions then its element will not be in a group.
                    * By default groups may contain different numbers of
                      elements.
                    * If no units are specified then the units of the
                      coordinates are assumed.
                    * If an element is selected by two or more queries
                      then the latest one in the sequence defines which
                      group it will be in.
    
            .. 
    
              * An `int` defining the number of elements in each
                group. The first group starts with the first axis
                element and spans the defined number of consecutive
                elements. Each susbsequent group immediately follows
                the preceeeding one.
    
                  *Parameter example:*
                    To define groups of 5 elements: ``group=5``.
    
                  *Note:*
                    * By default each group has the defined number of
                      elements, apart from the last group which may
                      contain fewer elements (see the *group_span*
                      parameter).
    
            .. 
    
              * A `numpy` array of integers defining groups. The array
                must have the same length as the axis to be collapsed
                and its sequence of values correspond to the axis
                elements. Each group contains the elements which
                correspond to a common non-negative integer value in
                the numpy array. Upon output, the collapsed axis is
                arranged in order of increasing group number. See the
                *regroup* parameter, which allows the creation of such
                a `numpy.array` for a given grouped collapse.
    
                  *Parameter example:*
                    For an axis of size 8, create two groups, the
                    first containing the first and last elements and
                    the second containing the 3rd, 4th and 5th
                    elements, whilst ignoring the 2nd, 6th and 7th
                    elements: ``group=numpy.array([0, -1, 4, 4, 4, -1,
                    -2, 0])``.
    
                  *Note:* 
                    * The groups do not have to be in runs of consective
                      elements; they may be scattered throughout the axis.
                    * An element which corresponds to a negative integer
                      in the array will not be in any group.
    
        group_by: `str`, optional
            Specify how coordinates are assigned to the groups defined
            by the *group*, *within_days* or *within_years*
            parameter. Ignored unless one of these parameters is a
            `Data` or `TimeDuration` object. The *group_by* parameter
            may be one of:
    
              * ``'coords'``. This is the default. Each group contains
                the axis elements whose coordinate values lie within
                the group limits. Every element will be in a group.
    
            ..
    
              * ``'bounds'``. Each group contains the axis elements
                whose upper and lower coordinate bounds both lie
                within the group limits. Some elements may not be
                inside any group, either because the group limits do
                not coincide with coordinate bounds or because the
                group size is sufficiently small.
    
        group_span: optional
            Ignore groups whose span is less than a given value. By
            default all groups are collapsed, regardless of their
            size. Groups are defined by the *group*, *within_days* or
            *within_years* parameter.
    
            In general, the span of a group is the absolute difference
            between the lower bound of its first element and the upper
            bound of its last element. The only exception to this
            occurs if *group_span* is an integer, in which case the
            span of a group is the number of elements in the group.
    
              *Note:*
                * To also ensure that elements within a group are
                  contiguous, use the *group_contiguous* parameter.
    
            The *group_span* parameter may be one of:
    
              * `True`. Ignore groups whose span is less than the size
                defined by the *group* parameter. Only applicable if
                the *group* parameter is set to a `Data`,
                `TimeDuration` or `int` object. If the *group*
                parameter is a (sequence of) `Query` then one of the
                other options is required.
    
                  *Parameter example:*
                    To collapse into groups of 10 km, ignoring any
                    groups that span less than that distance:
                    ``group=cf.Data(10, 'km'), group_span=True``.
    
                  *Parameter example:*
                    To collapse a daily timeseries into monthly
                    groups, ignoring any groups that span less than 1
                    calendar month: monthly values: ``group=cf.M(),
                    group_span=True`` (see `cf.M`).
    
            ..
    
              * `Data`. Ignore groups whose span is less than the
                given size. If no units are specified then the units
                of the coordinates are assumed.
    
            ..
                
              * `TimeDuration`. Ignore groups whose span is less
                than the given time duration.
    
                  *Parameter example:*
                    To collapse a timeseries into seasonal groups,
                    ignoring any groups that span less than three
                    months: ``group=cf.seasons(), group_span=cf.M(3)``
                    (see `cf.seasons` and `cf.M`).
    
            ..
                
              * `int`. Ignore groups that contain fewer than the given
                number of elements.
    
        group_contiguous: `int`, optional
            Only applicable to grouped collapses (i.e. the *group*,
            *within_days* or *within_years* parameter is being
            used). If set to 1 or 2 then ignore groups whose cells are
            not contiguous along the collapse axis. By default,
            *group_contiguous* is 0, meaning that non-contiguous
            groups are allowed. The *group_contiguous* parameter may
            be one of:
    
              ===================  =======================================
              *group_contiguous*   Description
              ===================  =======================================
              ``0``                Allow non-contiguous groups.
    
              ``1``                Ignore non-contiguous groups, as well
                                   as contiguous groups containing
                                   overlapping cells.
    
              ``2``                Ignore non-contiguous groups, allowing
                                   contiguous groups containing
                                   overlapping cells.
              ===================  =======================================
    
              *Parameter example:*
                To ignore non-contiguous groups, as well as any
                contiguous group containing overlapping cells:
                ``group_contiguous=1``.
    
        regroup: `bool`, optional
            For grouped collapses, return a `numpy.array` of integers
            which identifies the groups defined by the *group*
            parameter. The array is interpreted as for a numpy array
            value of the *group* parameter, and thus may subsequently
            be used by *group* parameter in a separate collapse. For
            example:
    
            >>> groups = f.collapse('time: mean', group=10, regroup=True)
            >>> g = f.collapse('time: mean', group=groups)
    
            is equivalent to:
    
            >>> g = f.collapse('time: mean', group=10)
    
        within_days: optional
            Independently collapse groups of reference-time axis
            elements for CF "within days" climatological
            statistics. Each group contains elements whose coordinates
            span a time interval of up to one day. Upon output, the
            results of the collapses are concatenated so that the
            output axis has a size equal to the number of groups.
    
            *Note:*
              For CF compliance, a "within days" collapse should be
              followed by an "over days" collapse.
    
            The *within_days* parameter defines how the elements are
            partitioned into groups, and may be one of:
    
              * A `TimeDuration` defining the group size in terms
                of a time interval of up to one day. The first group
                starts at or before the first coordinate bound of the
                first axis element (or its coordinate if there are no
                bounds) and spans the defined group size. Each
                susbsequent group immediately follows the preceeeding
                one. By default each group contains the consective run
                of elements whose coordinate values lie within the
                group limits (see the *group_by* parameter).
    
                  *Parameter example:*
                    To define groups of 6 hours, starting at 00:00,
                    06:00, 12:00 and 18:00: ``within_days=cf.h(6)``
                    (see `cf.h`).
    
                  *Parameter example:*
                    To define groups of 1 day, starting at 06:00:
                    ``within_days=cf.D(1, hour=6)`` (see `cf.D`).
    
                  *Note:*
                    * Groups may contain different numbers of elements.
                    * The start of the first group may be before the first
                      first axis element, depending on the offset defined
                      by the time duration. For example, if
                      ``group=cf.D(hour=12)`` then the first group will
                      start on the closest midday to the first axis
                      element.
    
            ..
    
              * A (sequence of) `Query`, each of which is a
                condition defining one or more groups. Each query
                selects elements whose coordinates satisfy its
                condition and from these elements multiple groups are
                created - one for each maximally consecutive run
                within these elements.
    
                  *Parameter example:*
                    To define groups of 00:00 to 06:00 within each
                    day, ignoring the rest of each day:
                    ``within_days=cf.hour(cf.le(6))`` (see `cf.hour`
                    and `cf.le`).
    
                  *Parameter example:*
                    To define groups of 00:00 to 06:00 and 18:00 to
                    24:00 within each day, ignoring the rest of each
                    day: ``within_days=[cf.hour(cf.le(6)),
                    cf.hour(cf.gt(18))]`` (see `cf.gt`, `cf.hour` and
                    `cf.le`).
    
                  *Note:*
                    * Groups may contain different numbers of elements.
                    * If no units are specified then the units of the
                      coordinates are assumed.
                    * If a coordinate does not satisfy any of the
                      conditions then its element will not be in a group.
                    * If an element is selected by two or more queries
                      then the latest one in the sequence defines which
                      group it will be in.
    
        within_years: optional 
            Independently collapse groups of reference-time axis
            elements for CF "within years" climatological
            statistics. Each group contains elements whose coordinates
            span a time interval of up to one calendar year. Upon
            output, the results of the collapses are concatenated so
            that the output axis has a size equal to the number of
            groups.
    
              *Note:*
                For CF compliance, a "within years" collapse should be
                followed by an "over years" collapse.
    
            The *within_years* parameter defines how the elements are
            partitioned into groups, and may be one of:
    
              * A `TimeDuration` defining the group size in terms of a
                time interval of up to one calendar year. The first
                group starts at or before the first coordinate bound
                of the first axis element (or its coordinate if there
                are no bounds) and spans the defined group size. Each
                susbsequent group immediately follows the preceeeding
                one. By default each group contains the consective run
                of elements whose coordinate values lie within the
                group limits (see the *group_by* parameter).
    
                  *Parameter example:*
                    To define groups of 90 days:
                    ``within_years=cf.D(90)`` (see `cf.D`).
    
                  *Parameter example:*  
                    To define groups of 3 calendar months, starting on
                    the 15th of a month: ``within_years=cf.M(3,
                    day=15)`` (see `cf.M`).
    
                  *Note:*
                    * Groups may contain different numbers of elements.
                    * The start of the first group may be before the first
                      first axis element, depending on the offset defined
                      by the time duration. For example, if
                      ``group=cf.Y(month=12)`` then the first group will
                      start on the closest 1st December to the first axis
                      element.
    
            ..
    
              * A (sequence of) `Query`, each of which is a
                condition defining one or more groups. Each query
                selects elements whose coordinates satisfy its
                condition and from these elements multiple groups are
                created - one for each maximally consecutive run
                within these elements.
    
                  *Parameter example:*
                    To define groups for the season MAM within each
                    year: ``within_years=cf.mam()`` (see `cf.mam`).
    
                  *Parameter example:*
                    To define groups for February and for November to
                    December within each year:
                    ``within_years=[cf.month(2),
                    cf.month(cf.ge(11))]`` (see `cf.month` and
                    `cf.ge`).
    
                  *Note:*
                    * The first group may start outside of the range of
                      coordinates (the start of the first group is
                      controlled by parameters of the `TimeDuration`).
                    * If group boundaries do not coincide with coordinate
                      bounds then some elements may not be inside any
                      group.
                    * If the group size is sufficiently small then some
                      elements may not be inside any group.
                    * Groups may contain different numbers of elements.
    
        over_days: optional
            Independently collapse groups of reference-time axis
            elements for CF "over days" climatological
            statistics. Each group contains elements whose coordinates
            are **matching**, in that their lower bounds have a common
            time of day but different dates of the year, and their
            upper bounds also have a common time of day but different
            dates of the year. Upon output, the results of the
            collapses are concatenated so that the output axis has a
            size equal to the number of groups.
    
              *Parameter example:*
                An element with coordinate bounds {1999-12-31
                06:00:00, 1999-12-31 18:00:00} **matches** an element
                with coordinate bounds {2000-01-01 06:00:00,
                2000-01-01 18:00:00}.
    
              *Parameter example:*
                An element with coordinate bounds {1999-12-31
                00:00:00, 2000-01-01 00:00:00} **matches** an element
                with coordinate bounds {2000-01-01 00:00:00,
                2000-01-02 00:00:00}.
    
              *Note:*       
                * A *coordinate* parameter value of ``'min'`` is
                  assumed, regardless of its given value.
                 
                * A *group_by* parameter value of ``'bounds'`` is
                  assumed, regardless of its given value.
                
                * An "over days" collapse must be preceded by a
                  "within days" collapse, as described by the CF
                  conventions. If the field already contains sub-daily
                  data, but does not have the "within days" cell
                  methods flag then it may be added, for example, as
                  follows (this example assumes that the appropriate
                  cell method is the most recently applied, which need
                  not be the case; see `cf.CellMethods` for details):
                
                  >>> f.cell_methods[-1].within = 'days'
    
            The *over_days* parameter defines how the elements are
            partitioned into groups, and may be one of:
    
              * `None`. This is the default. Each collection of
              **matching** elements forms a group.
    
            ..
    
              * A `TimeDuration` object defining the group size in
                terms of a time duration of at least one day. Multiple
                groups are created from each collection of
                **matching** elements - the first of which starts at
                or before the first coordinate bound of the first
                element and spans the defined group size. Each
                susbsequent group immediately follows the preceeeding
                one. By default each group contains the **matching**
                elements whose coordinate values lie within the group
                limits (see the *group_by* parameter).
    
                  *Parameter example:*
                    To define groups spanning 90 days:
                    ``over_days=cf.D(90)`` or
                    ``over_days=cf.h(2160)``. (see `cf.D` and `cf.h`).
    
                  *Parameter example:*
                    To define groups spanning 3 calendar months,
                    starting and ending at 06:00 in the first day of
                    each month: ``over_days=cf.M(3, hour=6)`` (see
                    `cf.M`).
    
                  *Note:*
                    * Groups may contain different numbers of elements.
                    * The start of the first group may be before the first
                      first axis element, depending on the offset defined
                      by the time duration. For example, if
                      ``group=cf.M(day=15)`` then the first group will
                      start on the closest 15th of a month to the first
                      axis element.
    
            ..
    
              * A (sequence of) `Query`, each of which is a
                condition defining one or more groups. Each query
                selects elements whose coordinates satisfy its
                condition and from these elements multiple groups are
                created - one for each subset of **matching**
                elements.
    
                  *Parameter example:*
                    To define groups for January and for June to
                    December, ignoring all other months:
                    ``over_days=[cf.month(1), cf.month(cf.wi(6,
                    12))]`` (see `cf.month` and `cf.wi`).
    
                  *Note:*
                    * If a coordinate does not satisfy any of the
                      conditions then its element will not be in a group.
                    * Groups may contain different numbers of elements.
                    * If an element is selected by two or more queries
                      then the latest one in the sequence defines which
                      group it will be in.
    
        over_years: optional
            Independently collapse groups of reference-time axis
            elements for CF "over years" climatological
            statistics. Each group contains elements whose coordinates
            are **matching**, in that their lower bounds have a common
            sub-annual date but different years, and their upper
            bounds also have a common sub-annual date but different
            years. Upon output, the results of the collapses are
            concatenated so that the output axis has a size equal to
            the number of groups.
    
              *Parameter example:*
                An element with coordinate bounds {1999-06-01
                06:00:00, 1999-09-01 06:00:00} **matches** an element
                with coordinate bounds {2000-06-01 06:00:00,
                2000-09-01 06:00:00}.
    
              *Parameter example:*
                An element with coordinate bounds {1999-12-01
                00:00:00, 2000-12-01 00:00:00} **matches** an element
                with coordinate bounds {2000-12-01 00:00:00,
                2001-12-01 00:00:00}.
    
              *Note:*       
                * A *coordinate* parameter value of ``'min'`` is
                  assumed, regardless of its given value.
                 
                * A *group_by* parameter value of ``'bounds'`` is
                  assumed, regardless of its given value.
                
                * An "over years" collapse must be preceded by a
                  "within years" or an "over days" collapse, as
                  described by the CF conventions. If the field
                  already contains sub-annual data, but does not have
                  the "within years" or "over days" cell methods flag
                  then it may be added, for example, as follows (this
                  example assumes that the appropriate cell method is
                  the most recently applied, which need not be the
                  case; see `cf.CellMethods` for details):
    
                  >>> f.cell_methods[-1].over = 'days'
    
            The *over_years* parameter defines how the elements are
            partitioned into groups, and may be one of:
    
              * `None`. Each collection of **matching** elements forms
                a group. This is the default.
    
            ..
    
              * A `TimeDuration` object defining the group size in
                terms of a time interval of at least one calendar
                year. Multiple groups are created from each collection
                of **matching** elements - the first of which starts
                at or before the first coordinate bound of the first
                element and spans the defined group size. Each
                susbsequent group immediately follows the preceeeding
                one. By default each group contains the **matching**
                elements whose coordinate values lie within the group
                limits (see the *group_by* parameter).
    
                  *Parameter example:*
                    To define groups spanning 10 calendar years:
                    ``over_years=cf.Y(10)`` or
                    ``over_years=cf.M(120)`` (see `cf.M` and `cf.Y`).
    
                  *Parameter example:*
                    To define groups spanning 5 calendar years,
                    starting and ending at 06:00 on 01 December of
                    each year: ``over_years=cf.Y(5, month=12,
                    hour=6)`` (see `cf.Y`).
    
                  *Note:*
                    * Groups may contain different numbers of elements.
                    * The start of the first group may be before the first
                      first axis element, depending on the offset defined
                      by the time duration. For example, if
                      ``group=cf.Y(month=12)`` then the first group will
                      start on the closest 1st December to the first axis
                      element.
    
            ..
    
              * A (sequence of) `Query`, each of which is a condition
                defining one or more groups. Each query selects elements
                whose coordinates satisfy its condition and from these
                elements multiple groups are created - one for each subset
                of **matching** elements.
    
                  *Parameter example:*
                    To define one group spanning 1981 to 1990 and another
                    spanning 2001 to 2005:
                    ``over_years=[cf.year(cf.wi(1981, 1990),
                    cf.year(cf.wi(2001, 2005)]`` (see `cf.year` and
                    `cf.wi`).
    
                  *Note:*
                    * If a coordinate does not satisfy any of the
                      conditions then its element will not be in a group.
                    * Groups may contain different numbers of elements.
                    * If an element is selected by two or more queries
                      then the latest one in the sequence defines which
                      group it will be in.
    
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        kwargs: deprecated at version 3.0.0
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
    :Returns:
     
        `Field` or `numpy.ndarray`
             The collapsed field. Alternatively, if the *regroup*
             parameter is `True` then a numpy array is returned.

    **Examples:**

    See the on-line documention for further worked examples
    (TODOile:///home/david/cf-python/docs/dev/tutorial.html#statistical-collapses)

    '''        
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'collapse', i=True) # pragma: no cover

        if _debug:
            _DEPRECATION_ERROR_KWARGS(self, 'collapse', {'_debug': _debug},
                                      "Use keyword 'verbose' instead.") # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'collapse', kwargs) # pragma: no cover

        if inplace:
            f = self
        else:
            f = self.copy()

        # Whether or not to create null bounds for null
        # collapses. I.e. if the collapse axis has size 1 and no
        # bounds, whether or not to create upper and lower bounds to
        # the coordinate value. If this occurs it's because the null
        # collapse is part of a grouped collapse and so will be
        # concatenated to other collapses for the final result: bounds
        # will be made for the grouped collapse, so all elements need
        # bounds.
#        _create_zero_size_cell_bounds = kwargs.get('_create_zero_size_cell_bounds', False)

        # ------------------------------------------------------------
        # Parse the methods and axes
        # ------------------------------------------------------------
        if ':' in method:
            # Convert a cell methods string (such as 'area: mean dim3:
            # dim2: max T: minimum height: variance') to a CellMethods
            # object
            if axes is not None:
                raise ValueError(
                    "Can't collapse: Can't set 'axes' when 'method' is CF-like cell methods string")

            all_methods = []
            all_axes    = []
            all_within  = []
            all_over    = []

            for cm in CellMethod.create(method):        
                all_methods.append(cm.get_method(None))
                all_axes.append(cm.get_axes(()))
                all_within.append(cm.get_qualifier('within', None))
                all_over.append(cm.get_qualifier('over', None))
        else:            
            x = method.split(' within ')
            if method == x[0]:
                within = None
                x = method.split(' over ')
                if method == x[0]:
                    over = None
                else:
                    method, over = x
            else:
                method, within = x
           
            if isinstance(axes, (str, int)):
                axes = (axes,)

            all_methods = (method,)
            all_within  = (within,)
            all_over    = (over,)
            all_axes    = (axes,)

        # ------------------------------------------------------------
        # Convert axes into domain axis construct keys
        # ------------------------------------------------------------
        input_axes = all_axes
        all_axes = []
        for axes in input_axes:
            if axes is None:
                all_axes.append(list(self.domain_axes.keys()))
                continue

            axes2 = []
            for axis in axes:
                if axis == 'area':
                    for x in ('X', 'Y'):
                        a = self.domain_axis(x, key=True, default=None)
                        if a is None:
                            raise ValueError(
                                "Must have 'X' and 'Y' axes for an 'area' collapse. Can't find {!r} axis".format(x))

                        axes2.append(a)
                elif axis == 'volume':
                    for x in ('X', 'Y', 'Z'):
                        a = self.domain_axis(x, key=True, default=None)
                        if a is None:
                            raise ValueError(
                                "Must have 'X', 'Y' and 'Z' axes for a 'volume' collapse. Can't find {!r} axis".format(x))
                        
                        axes2.append(a)
                else:
                    a = self.domain_axis(axis, key=True, default=None)
                    if a is None:
                        raise ValueError("Can't find the collapse axis identified by {!r}".format(axis))
                    
                    axes2.append(a)
            #--- End: for
            
            all_axes.append(axes2)
        #--- End: for

        if verbose:
            print('    all_methods, all_axes, all_within, all_over =', \
                  all_methods, all_axes, all_within, all_over) # pragma: no cover

        if group is not None and len(all_axes) > 1:
            raise ValueError(
                "Can't use group parameter for multiple collapses")

        # ------------------------------------------------------------
        #
        # ------------------------------------------------------------
        for method, axes, within, over, axes_in in zip(all_methods,
                                                       all_axes,
                                                       all_within,
                                                       all_over,
                                                       input_axes):

            method2 = _collapse_methods.get(method, None)
            if method2 is None:
                raise ValueError(
                    "Can't collapse: Unknown method: {!r}".format(method))

            method = method2

            collapse_axes_all_sizes = f.domain_axes.filter_by_key(*axes)
                
            if verbose:
                print('    axes                    =', axes) # pragma: no cover
                print('    method                  =', method) # pragma: no cover
                print('    collapse_axes_all_sizes =', collapse_axes_all_sizes) # pragma: no cover

            if not collapse_axes_all_sizes:
                raise ValueError("Can't collapse: Can not identify collapse axes")

            if method not in ('sample_size', 'sum_of_weights', 'sum_of_weights2'):
                collapse_axes = collapse_axes_all_sizes.filter_by_size(gt(1))
            else:
                collapse_axes = collapse_axes_all_sizes.copy()

            if verbose:
                print('    collapse_axes           =', collapse_axes) # pragma: no cover

            if not collapse_axes:
               # Do nothing if there are no collapse axes
                if _create_zero_size_cell_bounds:
                    # Create null bounds if requested
                    for axis in axes:
                        dc = f.dimension_coordinates.filter_by_axis('and', axis).value(None)
                        if dc is not None and not dc.has_bounds():
                            dc.set_bounds(dc.create_bounds(cellsize=0))
#                    for axis in f.axes(axes):
#                        d = f.item(axes, role='d')
#                        if d and not d.has_bounds():
#                            d.get_bounds(create=True, insert=True, cellsize=0)
                #--- End: if
                
                continue
    
            # Check that there are enough elements to collapse
            collapse_axes_sizes = [da.get_size() for da in collapse_axes.values()]
            size = reduce(operator_mul, collapse_axes_sizes, 1)
            min_size = _collapse_min_size.get(method, 1)
            if size < min_size:
                raise ValueError("Can't calculate {0} from fewer than {1} values".format(
                    _collapse_cell_methods[method], min_size))

            if verbose:
                print('    collapse_axes_sizes     =', collapse_axes_sizes) # pragma: no cover

            grouped_collapse = (within is not None or
                                over   is not None or
                                group  is not None)

            if grouped_collapse:
                if len(collapse_axes) > 1:
                    raise ValueError("Can't do a grouped collapse multiple axes simultaneously")

                # ------------------------------------------------------------
                # Calculate weights
                # ------------------------------------------------------------
                g_weights = weights
                if method in _collapse_weighted_methods:
                    g_weights = f.weights(weights, scale=True, components=True)
                    if not g_weights:
                        g_weights = None
                #--- End: if

                axis = collapse_axes.key()
                
                f = f._collapse_grouped(method,
                                        axis,
                                        within=within,
                                        over=over,
                                        within_days=within_days,
                                        within_years=within_years,
                                        over_days=over_days,
                                        over_years=over_years,
                                        group=group,
                                        group_span=group_span,
                                        group_contiguous=group_contiguous,
                                        regroup=regroup,
                                        mtol=mtol,
                                        ddof=ddof,
                                        weights=g_weights,
                                        squeeze=squeeze,
                                        coordinate=coordinate,
                                        group_by=group_by,
                                        verbose=verbose)

                if regroup:
                    # Return the numpy array
                    return f
                
                # ----------------------------------------------------
                # Update the cell methods
                # ----------------------------------------------------
                f._collapse_update_cell_methods(method=method,
                                                collapse_axes=collapse_axes,
                                                input_axes=axes_in,
                                                within=within,
                                                over=over,
                                                verbose=verbose)                
                continue
            elif regroup:
                raise ValueError(
                    "Can't return an array of groups for a non-grouped collapse")

            if group_contiguous:
                raise ValueError(
                    "Can't collapse: Can only set group_contiguous for grouped, 'within days' or 'within years' collapses.")
            
            if group_span is not None:
                raise ValueError(
                    "Can't collapse: Can only set group_span for grouped, 'within days' or 'within years' collapses.")
            
#            method = _collapse_methods.get(method, None)
#            if method is None:
#                raise ValueError("uih luh hbblui")
#
#            # Check that there are enough elements to collapse
#            size = reduce(operator_mul, domain.axes_sizes(collapse_axes).values())
#            min_size = _collapse_min_size.get(method, 1)
#            if size < min_size:
#                raise ValueError(
#                    "Can't calculate %s from fewer than %d elements" %
#                    (_collapse_cell_methods[method], min_size))
    
            data_axes = f.get_data_axes()
            iaxes = [data_axes.index(axis) for axis in collapse_axes]

            # ------------------------------------------------------------
            # Calculate weights
            # ------------------------------------------------------------
            if verbose:
                print('    Input weights           =', repr(weights)) # pragma: no cover
                    
            d_kwargs = {}
            if weights is not None:
                if method in _collapse_weighted_methods:
                    d_weights = f.weights(weights, scale=True, components=True)
                    if d_weights:
                        d_kwargs['weights'] = d_weights
                elif not equals(weights, 'auto'):  # doc this
                    for x in iaxes:
                        if (x,) in d_kwargs:
                            raise ValueError(
"Can't collapse: Can't weight {!r} collapse method".format(method))

            #--- End: if

            if method in _collapse_ddof_methods:
                d_kwargs['ddof'] = ddof

            # ========================================================
            # Collapse the data array
            # ========================================================
            if verbose:
                print('  Before collapse of data:') # pragma: no cover
                print('    iaxes, d_kwargs =', iaxes, d_kwargs) # pragma: no cover
                print('    f.shape = ', f.shape) # pragma: no cover
                print('    f.dtype = ', f.dtype) # pragma: no cover

            getattr(f.data, method)(axes=iaxes, squeeze=squeeze, mtol=mtol,
                                    inplace=True, **d_kwargs)

            if squeeze:
                # ----------------------------------------------------
                # Remove the collapsed axes from the field's list of
                # data array axes
                # ----------------------------------------------------
                f.set_data_axes([axis for axis in data_axes
                                 if axis not in collapse_axes])

            if verbose:
                print('  After collapse of data:') # pragma: no cover
                print('    f.shape = ', f.shape) # pragma: no cover
                print('    f.dtype = ', f.dtype) # pragma: no cover

            #---------------------------------------------------------
            # Update dimension coordinates, auxiliary coordinates,
            # cell measures and domain ancillaries
            # ---------------------------------------------------------
            if verbose:
                print('    collapse_axes =',collapse_axes) # pragma: no cover
                
            for axis, domain_axis in collapse_axes.items():
                # Ignore axes which are already size 1
                size = domain_axis.get_size()
                if size == 1:
                    continue
             
                # REMOVE all cell measures and domain ancillaries
                # which span this axis
                c = f.constructs.filter_by_type('cell_measure', 'domain_ancillary')
                for key, value in c.filter_by_axis('or', axis).items():
                    if verbose:
                        print('    Removing {!r}'.format(value)) # pragma: no cover

                    f.del_construct(key)
                    
#                f.remove_items(role=('m', 'c'), axes=axis)
    
                # REMOVE all 2+ dimensional auxiliary coordinates
                # which span this axis
                c = f.auxiliary_coordinates.filter_by_naxes(gt(1))
                for key in c.filter_by_axis('or', axis):
                    if verbose:
                        print('    Removing {!r}'.format(value)) # pragma: no cover
                        
                    f.del_construct(key)
#               f.remove_items(role=('a',), axes=axis, ndim=gt(1))
                    
                # REMOVE all 1 dimensional auxiliary coordinates which
                # span this axis and have different values in their
                # data array and bounds.
                #
                # KEEP, after changing their data arrays, all
                # one-dimensional auxiliary coordinates which span
                # this axis and have the same values in their data
                # array and bounds.
#                for key, aux in f.Items(role='a', axes=set((axis,)), ndim=1).items():
                for key, aux in f.auxiliary_coordinates.filter_by_axis('exact', axis).items():
                    if verbose:
                        print('key, aux =', key, repr(aux)) # pragma: no cover
                        
                    d = aux[0]

                    if aux.has_bounds() or (aux[:-1] != aux[1:]).any():
                        if verbose:
                            print('    Removing {!r}'.format(aux)) # pragma: no cover
                            
                        f.del_construct(key)
                    else:
                        # Change the data array for this auxiliary
                        # coordinate
                        aux.set_data(d.data, copy=False)
                        if d.has_bounds():
                            aux.bounds.set_data(d.bounds.data, copy=False)
                #--- End: for

                # Reset the axis size
#                ncdim = f._Axes[axis].ncdim
#                f._Axes[axis] = DomainAxis(1, ncdim=ncdim)
                f.domain_axes[axis].set_size(1)
                if verbose:
                    print('Changing axis size to 1:', axis) # pragma: no cover
                
#                dim = f.Items.get(axis, None)
                dim = f.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if dim is None:
                    continue

                # Create a new dimension coordinate for this axis
                if dim.has_bounds():
                    bounds_data = [dim.bounds.datum(0), dim.bounds.datum(-1)]
                else:
                    bounds_data = [dim.datum(0), dim.datum(-1)]

                units = dim.Units

                if coordinate == 'mid_range':
                    data = Data([(bounds_data[0] + bounds_data[1])*0.5], units=units)
                elif coordinate == 'min':
                    data = dim.data.min()
                elif coordinate == 'max':
                    data = dim.data.max()
                else:
                    raise ValueError(
                        "Can't collapse: Bad parameter value: coordinate={0!r}".format(
                            coordinate))

                bounds = Bounds(data=Data([bounds_data], units=units))

#                dim.insert_data(data, bounds=bounds, copy=False)
                dim.set_data(data, copy=False)
                dim.set_bounds(bounds, copy=False)
            #--- End: for

            # --------------------------------------------------------
            # Update the cell methods
            # --------------------------------------------------------
#            if kwargs.get('_update_cell_methods', True):
            if _update_cell_methods:
                f._collapse_update_cell_methods(method,
                                                collapse_axes=collapse_axes,
                                                input_axes=axes_in,
                                                within=within,
                                                over=over,
                                                verbose=verbose)
        #--- End: for

        # ------------------------------------------------------------
        # Return the collapsed field (or the classification array)
        # ------------------------------------------------------------
        return f
    #--- End: def

    def _collapse_grouped(self, method, axis, within=None, over=None,
                          within_days=None, within_years=None,
                          over_days=None, over_years=None, group=None,
                          group_span=None, group_contiguous=False,
#                          input_axis=None,
                          mtol=None, ddof=None,
                          regroup=None, coordinate=None, weights=None,
                          squeeze=None, group_by=None, verbose=False):
        '''TODO
        
    :Parameters:
    
        method: `str`
            TODO
    
        axis: `str`
            TODO
    
        over: `str`
            TODO
    
        within: `str`
            TODO
    
    '''
        def _ddddd(classification, n, lower, upper, increasing, coord,
                   group_by_coords, extra_condition): 
            '''TODO
    
        :Parameter:
        
            extra_condition: `Query`
        
        :Returns:
        
            `numpy.ndarray`, `int`, date-time, date-time

            '''         
            if group_by_coords:
                q = ge(lower) & lt(upper)
            else:
                q = (ge(lower, attr='lower_bounds') & 
                     le(upper, attr='upper_bounds'))
                
            if extra_condition:
                q &= extra_condition

            index = q.evaluate(coord).array
            classification[index] = n

            if increasing:
                lower = upper 
            else:
                upper = lower

            n += 1

            return classification, n, lower, upper


        def _time_interval(classification, n, coord, interval, lower,
                           upper, lower_limit, upper_limit, group_by,
                           extra_condition=None):
            '''TODO

        :Parameters:
        
            classification: `numpy.ndarray`
        
            n: `int`
        
            coord: `DimensionCoordinate`
        
            interval: `TimeDuration`
        
            lower: date-time object
        
            upper: date-time object
        
            lower_limit: `datetime`
        
            upper_limit: `datetime`
        
            group_by: `str`
        
            extra_condition: `Query`, optional
        
        :Returns:
        
            (`numpy.ndarray`, `int`)

            '''
            group_by_coords = (group_by == 'coords')

            if coord.increasing:
                # Increasing dimension coordinate 
                lower, upper = interval.bounds(lower)
                while lower <= upper_limit:
                    lower, upper = interval.interval(lower)
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, True,
                        coord, group_by_coords, extra_condition)
            else: 
                # Decreasing dimension coordinate
                lower, upper = interval.bounds(upper)
                while upper >= lower_limit:
                    lower, upper = interval.interval(upper, end=True)
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, False,
                        coord, group_by_coords, extra_condition)
            #--- End: if
                        
            return classification, n


        def _time_interval_over(classification, n, coord, interval,
                                lower, upper, lower_limit,
                                upper_limit, group_by,
                                extra_condition=None):
            '''TODO

        :Parameters:
        
            classification: `numpy.ndarray`
        
            n: `int`
        
            coord: `DimensionCoordinate`
        
            interval: `TimeDuration`
        
            lower: date-time
        
            upper: date-time
        
            lower_limit: date-time
        
            upper_limit: date-time
        
            group_by: `str`
        
            extra_condition: `Query`, optional
        
        :Returns:
        
            (`numpy.ndarray`, `int`)

            '''
            group_by_coords = (group_by == 'coords')

            if coord.increasing:
                # Increasing dimension coordinate 
#                lower, upper = interval.bounds(lower)
                upper = interval.interval(upper)[1]
                while lower <= upper_limit:
                    lower, upper = interval.interval(lower)
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, True,
                        coord, group_by_coords, extra_condition)
            else: 
                # Decreasing dimension coordinate
#                lower, upper = interval.bounds(upper)
                lower = interval.interval(upper, end=True)[0]
                while upper >= lower_limit:
                    lower, upper = interval.interval(upper, end=True)
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, False,
                        coord, group_by_coords, extra_condition)
            #--- End: if
                        
            return classification, n


        def _data_interval(classification, n,
                           coord, interval,
                           lower, upper,
                           lower_limit, upper_limit,
                           group_by,
                           extra_condition=None):
            '''TODO

        :Returns:

            `numpy.ndarray`, `int`

            '''          
            group_by_coords = group_by == 'coords'

            if coord.increasing:
                # Increasing dimension coordinate 
                lower= lower.squeeze()
                while lower <= upper_limit:
                    upper = lower + interval 
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, True,
                        coord, group_by_coords, extra_condition)
            else: 
                # Decreasing dimension coordinate
                upper = upper.squeeze()
                while upper >= lower_limit:
                    lower = upper - interval
                    classification, n, lower, upper = _ddddd(
                        classification, n, lower, upper, False,
                        coord, group_by_coords, extra_condition)
            #--- End: if
                        
            return classification, n


        def _selection(classification, n, coord, selection, parameter,
                       extra_condition=None, group_span=None,
                       within=False):
            '''TODO

        :Parameters:
        
            classification: `numpy.ndarray`
        
            n: `int`
            
            coord: `DimensionCoordinate`
        
            selection: sequence of `Query`
        
            parameter: `str`
                The name of the `cf.Field.collapse` parameter which
                defined *selection*. This is used in error messages.
        
                *Parameter example:*
                  ``parameter='within_years'``
        
            extra_condition: `Query`, optional
        
        :Returns:
        
            `numpy.ndarray`, `int`

            '''        
            # Create an iterator for stepping through each Query in
            # the selection sequence
            try:
                iterator = iter(selection)
            except TypeError:
                raise ValueError(
                    "Can't collapse: Bad parameter value: {}={!r}".format(
                        parameter, selection))
            
            for condition in iterator:
                if not isinstance(condition, Query):
                    raise ValueError(
                        "Can't collapse: {} sequence contains a non-{} object: {!r}".format(
                            parameter, Query.__name__, condition))
                                
                if extra_condition is not None:
                    condition &= extra_condition

                boolean_index = condition.evaluate(coord).array

                classification[boolean_index] = n
                n += 1

#                if group_span is not None:
#                    x = numpy_where(classification==n)[0]
#                    for i in range(1, max(1, int(float(len(x))/group_span))):
#                        n += 1
#                        classification[x[i*group_span:(i+1)*group_span]] = n
#                #--- End: if
                
#                n += 1
            #--- End: for

            return classification, n

        
        def _discern_runs(classification, within=False):
            '''TODO

        :Parameters:
        
            classification: `numpy.ndarray`
        
        :Returns:
        
            `numpy.ndarray`
    
                '''            
            x = numpy_where(numpy_diff(classification))[0] + 1
            if not x.size:
                if classification[0] >= 0:
                    classification[:] = 0
            
                return classification

            if classification[0] >= 0:
                classification[0:x[0]] = 0

            n = 1
            for i, j in (zip(x[:-1], x[1:])):
                if classification[i] >= 0:
                    classification[i:j] = n
                    n += 1
            #-- End: for
            
            if classification[x[-1]] >= 0:
                classification[x[-1]:] = n
                n += 1

            return classification


        def _discern_runs_within(classification, coord):
            '''TODO
            '''            
            size = classification.size
            if size < 2:
                return classification
          
            n = classification.max() + 1

            start = 0
            for i, c in enumerate(classification[:size-1]):
                if c < 0:
                    continue

                if not coord[i:i+2].contiguous(overlap=False):
                    classification[start:i+1] = n
                    start = i + 1
                    n += 1
            #--- End: for

            return classification

                        
        def _tyu(coord, group_by, time_interval):
            '''TODO

        :Parameters:
        
            coord: `cf.Coordinate`
                TODO

            group_by: `str`
                As for the *group_by* parameter of the `collapse` method.
        
            time_interval: `bool`
                If `True` then then return a tuple of date-time
                objects, rather than a tuple of `Data` objects.
        
        :Returns:
        
            4-`tuple` of date-time objects

            '''
            bounds = coord.get_bounds(None)
            if bounds is not None:
                lower_bounds = coord.lower_bounds
                upper_bounds = coord.upper_bounds
                lower = lower_bounds[0]
                upper = upper_bounds[0]
                lower_limit = lower_bounds[-1]
                upper_limit = upper_bounds[-1]
            elif group_by == 'coords':
                if coord.increasing:
                    lower = coord.data[0]
                    upper = coord.data[-1]
                else:
                    lower = coord.data[-1]
                    upper = coord.data[0]
                    
                lower_limit = lower
                upper_limit = upper
            else:
                raise ValueError(
                    "Can't collapse: {!r} coordinate bounds are required with group_by={!r}".format(
                        coord.identity(), group_by))
               
            if time_interval:
                units = coord.Units
                if units.isreftime:
                    lower       = lower.datetime_array[0]
                    upper       = upper.datetime_array[0]
                    lower_limit = lower_limit.datetime_array[0]
                    upper_limit = upper_limit.datetime_array[0]
                elif not units.istime:
                    raise ValueError(
                        "Can't group by {0} when coordinates have units {1!r}".format(
                            TimeDuration.__name__, coord.Units))
            #--- End: if

            return (lower, upper, lower_limit, upper_limit)

    
        def _group_weights(weights, iaxis, index):
            '''TODO
            
        Subspace weights components.
        
            :Parameters:
        
                weights: `dict` or None
        
                iaxis: `int`
        
                index: `list`
        
            :Returns:
        
                `dict` or `None`
        
            **Examples:** 
        
            >>> print(weights)
            None
            >>> print(_group_weights(weights, 2, [2, 3, 40]))
            None
            >>> print(_group_weights(weights, 1, slice(2, 56)))
            None
        
            >>> weights
            
            >>> _group_weights(weights, 2, [2, 3, 40])
            
            >>> _group_weights(weights, 1, slice(2, 56))    
    
    
        '''
            if not isinstance(weights, dict):
                return weights

            weights = weights.copy()
            for iaxes, value in weights.items():
                if iaxis in iaxes:
                    indices = [slice(None)] * len(iaxes)
                    indices[iaxes.index(iaxis)] = index
                    weights[iaxes] = value[tuple(indices)]
                    break
            #--- End: for

            return weights

        
        # START OF MAIN CODE        

        if verbose:
            print('    Grouped collapse:')                               # pragma: no cover
            print('        method            =', repr(method)          ) # pragma: no cover
            print('        axis              =', repr(axis)            ) # pragma: no cover
            print('        over              =', repr(over)            ) # pragma: no cover
            print('        over_days         =', repr(over_days)       ) # pragma: no cover
            print('        over_years        =', repr(over_years)      ) # pragma: no cover
            print('        within            =', repr(within)          ) # pragma: no cover
            print('        within_days       =', repr(within_days)     ) # pragma: no cover
            print('        within_years      =', repr(within_years)    ) # pragma: no cover
            print('        regroup           =', repr(regroup)         ) # pragma: no cover
            print('        group             =', repr(group)           ) # pragma: no cover
            print('        group_span        =', repr(group_span)      ) # pragma: no cover
            print('        group_contiguous  =', repr(group_contiguous)) # pragma: no cover

        axis_size = self.domain_axes[axis].get_size()  # Size of uncollapsed axis
        iaxis     = self.get_data_axes().index(axis)   # Integer position of collapse axis

        fl = []

        # If group, rolling window, classification, etc, do something
        # special for size one axes - either return unchanged
        # (possibly mofiying cell methods with , e.g, within_dyas', or
        # raising an exception for 'can't match', I suppose.

        classification = None

        if group is not None:
            if within is not None or over is not None:
                raise ValueError(
                    "Can't set 'group' parameter for a climatological collapse")

            if isinstance(group, numpy_ndarray):
                classification = numpy_squeeze(group.copy())
#                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value()

                if classification.dtype.kind != 'i':
                    raise ValueError(
                        "Can't group by numpy array of type {}".format(classification.dtype.name))
                elif classification.shape != (axis_size,):
                    raise ValueError(
                        "Can't group by numpy array with incorrect shape: {}".format(
                            classification.shape))

                # Set group to None
                group = None
        #-- End: if

        if group is not None:
            if isinstance(group, Query):
                group = (group,)

            if isinstance(group, int):
                # ----------------------------------------------------
                # E.g. group=3
                # ----------------------------------------------------
                coord = None
                classification = numpy_empty((axis_size,), int)
                
                start = 0
                end   = group
                n = 0
                while start < axis_size:
                    classification[start:end] = n
                    start = end
                    end  += group
                    n += 1
                #--- End: while

                if group_span is True:
                    # Use the group definition as the group span
                    group_span = group
                    
            elif isinstance(group, TimeDuration):
                # ----------------------------------------------------
                # E.g. group=cf.M()
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None:
                    raise ValueError("dddddd siduhfsuildfhsuil dhfdui TODO") 
                     
                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)

                lower, upper, lower_limit, upper_limit = _tyu(coord, group_by, True)

                classification, n = _time_interval(classification, 0,
                                                   coord=coord,
                                                   interval=group,
                                                   lower=lower,
                                                   upper=upper,
                                                   lower_limit=lower_limit,
                                                   upper_limit=upper_limit,
                                                   group_by=group_by)

                if group_span is True:
                    # Use the group definition as the group span
                    group_span = group
                
            elif isinstance(group, Data):
                # ----------------------------------------------------
                # Chunks of 
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None:
                    raise ValueError("TODO dddddd siduhfsuildfhsuil dhfdui ") 

                if coord.Units.isreftime:
                    raise ValueError(
                        "Can't group a reference-time axis with {!r}. Use a TimeDuration instance instead.".format(
                            group))
                
                if group.size != 1:
                    raise ValueError("Group must have only one element: {!r}".format(group))

                if group.Units and not group.Units.equivalent(coord.Units):
                    raise ValueError(
                        "Can't group by {!r} when coordinates have non-equivalent units {!r}".format(
                            group, coord.Units))

                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)

                group = group.squeeze()
  
                lower, upper, lower_limit, upper_limit = _tyu(coord, group_by, False)

                classification, n = _data_interval(classification, 0,
                                                   coord=coord,
                                                   interval=group,
                                                   lower=lower,
                                                   upper=upper,
                                                   lower_limit=lower_limit,
                                                   upper_limit=upper_limit,
                                                   group_by=group_by)

                if group_span is True:
                    # Use the group definition as the group span
                    group_span = group

            else:
                # ----------------------------------------------------
                # E.g. group=[cf.month(4), cf.month(cf.wi(9, 11))]
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None:
#                    coord = self.aux(axes=axis, ndim=1)
                    coord = self.auxiliary_coordinates.filter_by_axis('exact', axis).value(None)
                    if coord is None:
                        raise ValueError("asdad8777787 TODO")
                #---End: if

                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)
                
                classification, n = _selection(classification, 0,
                                               coord=coord,
                                               selection=group,
                                               parameter='group')
                
                classification = _discern_runs(classification)
                
                if group_span is True:
                    raise ValueError(
"Can't collapse: Can't set group_span=True when group={!r}".format(group))
            #--- End: if
        #--- End: if
                  
        if classification is None:
            if over == 'days': 
                # ----------------------------------------------------
                # Over days
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None or not coord.Units.isreftime:
                    raise ValueError(
                        "Reference-time dimension coordinates are required for an 'over days' collapse")

                if not coord.has_bounds():
                    raise ValueError(
                        "Reference-time dimension coordinate bounds are required for an 'over days' collapse")

#                cell_methods = getattr(self, 'cell_methods', None)
#                cell_methods = self.cell_methods
#                if not cell_methods or 'days' not in cell_methods.within:
#                    raise ValueError(
#"Can't collapse: An 'over days' collapse must come after a 'within days' collapse")

                cell_methods = self.cell_methods.ordered()
                w = [cm.get_qualifier('within', None) for cm in cell_methods.values()]
                if 'days' not in w:
                    raise ValueError(
                        "An 'over days' collapse must come after a 'within days' cell method")


                # Parse the over_days parameter
                if isinstance(over_days, Query):
                    over_days = (over_days,)              
                elif isinstance(over_days, TimeDuration):
                    if over_days.Units.istime and over_days < Data(1, 'day'):
                        raise ValueError(
                            "Bad parameter value: over_days={!r}".format(over_days))
                #--- End: if
                    
                coordinate = 'min'
                
                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)
                
                if isinstance(over_days, TimeDuration):
                    lower, upper, lower_limit, upper_limit = _tyu(coord, group_by, True)

                bounds = coord.bounds
                lower_bounds = bounds.lower_bounds.datetime_array
                upper_bounds = bounds.upper_bounds.datetime_array

                HMS0 = None

#            * An "over days" collapse must be preceded by a "within
#              days" collapse, as described by the CF conventions. If the
#              field already contains sub-daily data, but does not have
#              the "within days" cell methods flag then it may be added,
#              for example, as follows (this example assumes that the
#              appropriate cell method is the most recently applied,
#              which need not be the case; see `cf.CellMethods` for
#              details):

#              >>> f.cell_methods[-1].within = 'days'

                n = 0
                for lower, upper in zip(lower_bounds, upper_bounds):
                    HMS_l = (eq(lower.hour  , attr='hour') & 
                             eq(lower.minute, attr='minute') & 
                             eq(lower.second, attr='second')).addattr('lower_bounds')
                    HMS_u = (eq(upper.hour  , attr='hour') & 
                             eq(upper.minute, attr='minute') & 
                             eq(upper.second, attr='second')).addattr('upper_bounds')
                    HMS = HMS_l & HMS_u

                    if not HMS0:
                        HMS0 = HMS
                    elif HMS.equals(HMS0):
                        break

                    if over_days is None:
                        # --------------------------------------------
                        # over_days=None
                        # --------------------------------------------
                        # Over all days
                        index = HMS.evaluate(coord).array
                        classification[index] = n
                        n += 1         
                    elif isinstance(over_days, TimeDuration):
                        # --------------------------------------------
                        # E.g. over_days=cf.M()
                        # --------------------------------------------
                        classification, n = _time_interval_over(classification, n,
                                                                coord=coord,
                                                                interval=over_days,
                                                                lower=lower,
                                                                upper=upper,
                                                                lower_limit=lower_limit,
                                                                upper_limit=upper_limit,
                                                                group_by=group_by,
                                                                extra_condition=HMS)
                    else:
                        # --------------------------------------------
                        # E.g. over_days=[cf.month(cf.wi(4, 9))]
                        # --------------------------------------------
                        classification, n = _selection(classification, n,
                                                       coord=coord,
                                                       selection=over_days,
                                                       parameter='over_days',
                                                       extra_condition=HMS)
                        
            elif over == 'years':
                # ----------------------------------------------------
                # Over years
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None or not coord.Units.isreftime:
                    raise ValueError(
                        "Reference-time dimension coordinates are required for an 'over years' collapse")
                
                bounds = coord.get_bounds(None)
                if bounds is None:
                    raise ValueError(
                        "Reference-time dimension coordinate bounds are required for an 'over years' collapse")
                
                cell_methods = self.cell_methods.ordered()
                w = [cm.get_qualifier('within', None) for cm in cell_methods.values()]
                o = [cm.get_qualifier('over', None)   for cm in cell_methods.values()]
                if 'years' not in w and 'days' not in o:
                    raise ValueError(
                        "An 'over years' collapse must come after a 'within years' or 'over days' cell method")

                # Parse the over_years parameter
                if isinstance(over_years, Query):
                    over_years = (over_years,)
                elif isinstance(over_years, TimeDuration):
                    if over_years.Units.iscalendartime:
                        over_years.Units = Units('calendar_years')
                        if not over_years.isint or over_years < 1:
                            raise ValueError(
                                "over_years is not a whole number of calendar years: {!r}".format(
                                    over_years))
                    else:
                        raise ValueError(
                            "over_years is not a whole number of calendar years: {!r}".format(
                                over_years))
                #--- End: if
                
                coordinate = 'min'
                
                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)
                
                if isinstance(over_years, TimeDuration):
                    _, _, lower_limit, upper_limit = _tyu(coord, group_by, True)

                lower_bounds = coord.lower_bounds.datetime_array
                upper_bounds = coord.upper_bounds.datetime_array
                mdHMS0 = None
                    
                n = 0
                for lower, upper in zip(lower_bounds, upper_bounds):
                    mdHMS_l = (eq(lower.month , attr='month') & 
                               eq(lower.day   , attr='day') & 
                               eq(lower.hour  , attr='hour') & 
                               eq(lower.minute, attr='minute') & 
                               eq(lower.second, attr='second')).addattr('lower_bounds')
                    mdHMS_u = (eq(upper.month , attr='month') & 
                               eq(upper.day   , attr='day') & 
                               eq(upper.hour  , attr='hour') & 
                               eq(upper.minute, attr='minute') & 
                               eq(upper.second, attr='second')).addattr('upper_bounds')
                    mdHMS = mdHMS_l & mdHMS_u

                    if not mdHMS0:
                        # Keep a record of the first cell
                        mdHMS0 = mdHMS
                        if verbose:
                            print('        mdHMS0 =', repr(mdHMS0)) # pragma: no cover
                    elif mdHMS.equals(mdHMS0):
                        # We've got repeat of the first cell, which
                        # means that we must have now classified all
                        # cells. Therefore we can stop.
                        break

                    if verbose:
                        print('        mdHMS  =', repr(mdHMS)) # pragma: no cover

                    if over_years is None:
                        # --------------------------------------------
                        # over_years=None
                        # --------------------------------------------
                        # Over all years
                        index = mdHMS.evaluate(coord).array
                        classification[index] = n
                        n += 1
                    elif isinstance(over_years, TimeDuration):
                        # --------------------------------------------
                        # E.g. over_years=cf.Y(2)
                        # --------------------------------------------
                        classification, n = _time_interval_over(classification, n,
                                                                coord=coord,
                                                                interval=over_years,
                                                                lower=lower,
                                                                upper=upper,
                                                                lower_limit=lower_limit,
                                                                upper_limit=upper_limit,
                                                                group_by=group_by,
                                                                extra_condition=mdHMS)
                    else:
                        # --------------------------------------------
                        # E.g. over_years=cf.year(cf.lt(2000))
                        # --------------------------------------------
                        classification, n = _selection(classification, n,
                                                       coord=coord,
                                                       selection=over_years,
                                                       parameter='over_years',
                                                       extra_condition=mdHMS)
                #--- End: for
    
            elif within == 'days':
                # ----------------------------------------------------
                # Within days
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
                if coord is None or not coord.Units.isreftime:
                    raise ValueError(
                        "Reference-time dimension coordinates are required for an 'over years' collapse")

                bounds = coord.get_bounds(None)
                if bounds is None:
                    raise ValueError(
                        "Reference-time dimension coordinate bounds are required for a 'within days' collapse")

                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)
    
                # Parse the within_days parameter
                if isinstance(within_days, Query):
                    within_days = (within_days,)
                elif isinstance(within_days, TimeDuration):
                    if within_days.Units.istime and Data(1, 'day') % within_days:
                        raise ValueError(
                            "Can't collapse: within_days={!r} is not an exact factor of 1 day".format(
                                within_days))
                #--- End: if

                if isinstance(within_days, TimeDuration):
                    # ------------------------------------------------
                    # E.g. within_days=cf.h(6)
                    # ------------------------------------------------ 
                    lower, upper, lower_limit, upper_limit = _tyu(coord, group_by, True)
                        
                    classification, n = _time_interval(classification, 0,
                                                       coord=coord,
                                                       interval=within_days,
                                                       lower=lower,
                                                       upper=upper,
                                                       lower_limit=lower_limit,
                                                       upper_limit=upper_limit,
                                                       group_by=group_by)
                    
                    if group_span is True:
                        # Use the within_days definition as the group
                        # span
                        group_span = within_days
                    
                else:
                    # ------------------------------------------------
                    # E.g. within_days=cf.hour(cf.lt(12))
                    # ------------------------------------------------
                    classification, n = _selection(classification, 0,
                                                   coord=coord,
                                                   selection=within_days,
                                                   parameter='within_days') 
                    
                    classification = _discern_runs(classification)

                    classification = _discern_runs_within(classification, coord)
     
                    if group_span is True:
                        raise ValueError(
                            "Can't collapse: Can't set group_span=True when within_days={!r}".format(
                                within_days))
                    
            elif within == 'years':
                # ----------------------------------------------------
                # Within years
                # ----------------------------------------------------
                coord = self.dimension_coordinates.filter_by_axis('exact', axis).value()
                if coord is None or not coord.Units.isreftime:
                    raise ValueError(
                        "Can't collapse: Reference-time dimension coordinates are required for a \"within years\" collapse")

                if not coord.has_bounds():
                    raise ValueError(
                        "Can't collapse: Reference-time dimension coordinate bounds are required for a \"within years\" collapse")

                classification = numpy_empty((axis_size,), int)
                classification.fill(-1)

                # Parse within_years
                if isinstance(within_years, Query):
                    within_years = (within_years,)               
                elif within_years is None:
                    raise ValueError(                        
                        'Must set the within_years parameter for a "within years" climatalogical time collapse')

                if isinstance(within_years, TimeDuration):
                    # ------------------------------------------------
                    # E.g. within_years=cf.M()
                    # ------------------------------------------------
                    lower, upper, lower_limit, upper_limit = _tyu(coord, group_by, True)
                        
                    classification, n = _time_interval(classification, 0,
                                                       coord=coord,
                                                       interval=within_years,
                                                       lower=lower,
                                                       upper=upper,
                                                       lower_limit=lower_limit,
                                                       upper_limit=upper_limit,
                                                       group_by=group_by)

                    if group_span is True:
                        # Use the within_years definition as the group
                        # span
                        group_span = within_years
                    
                else:
                    # ------------------------------------------------
                    # E.g. within_years=cf.season()
                    # ------------------------------------------------
                    classification, n = _selection(classification, 0,
                                                   coord=coord,
                                                   selection=within_years,
                                                   parameter='within_years',
                                                   within=True)
                    
                    classification = _discern_runs(classification, within=True)

                    classification = _discern_runs_within(classification, coord)

                    if group_span is True:
                        raise ValueError(
                            "Can't collapse: Can't set group_span=True when within_years={!r}".format(
                                within_years))
                    
            elif over is not None:
                raise ValueError(
                    "Can't collapse: Bad 'over' syntax: {!r}".format(over))
                
            elif within is not None: 
                raise ValueError(
                    "Can't collapse: Bad 'within' syntax: {!r}".format(within))
        #--- End: if
                 
        if classification is not None:
            #---------------------------------------------------------
            # Collapse each group
            #---------------------------------------------------------
            if verbose:
                print('        classification    =',classification) # pragma: no cover
                
            unique = numpy_unique(classification)
            unique = unique[numpy_where(unique >= 0)[0]]
            unique.sort()

            ignore_n = -1

            for u in unique:
                index = numpy_where(classification==u)[0].tolist()

                pc = self.subspace(**{axis: index})

                # ----------------------------------------------------
                # Ignore groups that don't meet the specified criteria
                # ----------------------------------------------------
                if over is None:
                    if group_span is not None:
                        if isinstance(group_span, int):
#                            if pc.axis_size(axis) != group_span:
                            if pc.domain_axes[axis].get_size() != group_span:
                                classification[index] = ignore_n
                                ignore_n -= 1
                                continue
                        else:
#                            coord = pc.coord(input_axis, ndim=1)
                            coord = pc.coordinates.filter_by_axis('exact', axis).value(None)
                            if coord is None:
                                raise ValueError(
                                    "Can't collapse: Need unambiguous 1-d coordinates when group_span={!r}".format(
                                        group_span))

                            bounds = coord.get_bounds(None)
                            if bounds is None:
                                raise ValueError(
                                    "Can't collapse: Need unambiguous 1-d coordinate bounds when group_span={!r}".format(
                                        group_span))

                            lb = bounds[ 0, 0].get_data()
                            ub = bounds[-1, 1].get_data()
                            if coord.T:
                                lb = lb.datetime_array.item()
                                ub = ub.datetime_array.item()
                            
                            if not coord.increasing:
                                lb, ub = ub, lb

                            if group_span + lb != ub:
                                # The span of this group is not the
                                # same as group_span, so don't
                                # collapse it.
                                classification[index] = ignore_n
                                ignore_n -= 1
                                continue
                        #--- End: if
                    #--- End: if
            
                    if group_contiguous:
                        overlap = (group_contiguous == 2)
                        if not coord.bounds.contiguous(overlap=overlap):
                            # This group is not contiguous, so don't
                            # collapse it.
                            classification[index] = ignore_n
                            ignore_n -= 1
                            continue                        
                #--- End: if

                if regroup:
                    continue

                # ----------------------------------------------------
                # Still here? Then collapse the group
                # ----------------------------------------------------
                w = _group_weights(weights, iaxis, index)
                if verbose:
                    print('        Collapsing group', u, ':', repr(pc)) # pragma: no cover

                fl.append(pc.collapse(method, axis, weights=w,
                                      mtol=mtol, ddof=ddof,
                                      coordinate=coordinate,
                                      squeeze=False, inplace=True,
                                      _create_zero_size_cell_bounds=True,
                                      _update_cell_methods=False))
            #--- End: for
            
            if regroup:
                # return the numpy array
                return classification

        elif regroup:
            raise ValueError("Can't return classification 2453456 ")

        # Still here?
        if not fl:
            c = 'contiguous ' if group_contiguous else ''
            s = ' spanning {}'.format(group_span) if group_span is not None else ''
            raise ValueError(
                "Can't collapse: No {}groups{} were identified".format(c, s))
            
        if len(fl) == 1:
            f = fl[0]
        else:
            # Hack to fix missing bounds!            
            for g in fl:
                try:
#                    g.dim(axis).get_bounds(create=True, insert=True, copy=False)
                    c = g.dimension_coordinates.filter_by_axis('exact', axis).value()
                    if not c.has_bounds():
                        c.set_bounds(c.create_bounds())
                except:
                    pass
            #--- End: for
            
            # --------------------------------------------------------
            # Sort the list of collapsed fields
            # --------------------------------------------------------
            if coord is not None and coord.isdimension:
#                fl.sort(key=lambda g: g.dim(axis).datum(0),
#                        reverse=coord.decreasing)
                fl.sort(
                    key=lambda g: g.dimension_coordinates.filter_by_axis('exact', axis).value().datum(0),
                    reverse=coord.decreasing)
                
            # --------------------------------------------------------
            # Concatenate the partial collapses
            # --------------------------------------------------------
            try:
                f = self.concatenate(fl, axis=iaxis, _preserve=False)
            except ValueError as error:
                raise ValueError("Can't collapse: {0}".format(error))
        #--- End: if
                      
        if squeeze and f.domain_axes[axis].get_size() == 1:
            # Remove a totally collapsed axis from the field's
            # data array
            f.squeeze(axis, inplace=True)

        # ------------------------------------------------------------
        # Return the collapsed field
        # ------------------------------------------------------------
        self.__dict__ = f.__dict__
        if verbose:
            print('    End of grouped collapse') # pragma: no cover
            
        return self


    def _collapse_update_cell_methods(self, method=None,
                                      collapse_axes=None,
                                      input_axes=None, within=None,
                                      over=None, verbose=False):
        '''Update the cell methods.

    :Parameters:
    
        method: `str`
    
        collapse_axes: `Constructs`
    
    :Returns:
    
        `None`

        '''
        original_cell_methods = self.cell_methods.ordered()
        if verbose:
            print('  Update cell methods:') # pragma: no cover
            print('    Original cell methods =', original_cell_methods) # pragma: no cover
            print('    method        =', repr(method)                 ) # pragma: no cover
            print('    within        =', repr(within)                 ) # pragma: no cover
            print('    over          =', repr(over)                   ) # pragma: no cover

        if input_axes and tuple(input_axes) == ('area',):
            axes = ('area',)
        else:
            axes   = tuple(collapse_axes)
            
        method = _collapse_cell_methods.get(method, method)

        cell_method = CellMethod(axes=axes, method=method)
        if within:
            cell_method.set_qualifier('within', within)
        elif over:
            cell_method.set_qualifier('over', over)

        if original_cell_methods:
            # There are already some cell methods
            if len(collapse_axes) == 1:
                # Only one axis has been collapsed
                key, original_domain_axis = tuple(collapse_axes.items())[0]
    
                lastcm = tuple(original_cell_methods.values())[-1]
                lastcm_method = _collapse_cell_methods.get(lastcm.get_method(None), lastcm.get_method(None))

                if original_domain_axis.get_size() == self.domain_axes[key].get_size():
                    if (lastcm.get_axes(None) == axes and
                        lastcm_method == method and
                        lastcm_method in ('mean', 'maximum', 'minimum', 'point',
                                          'sum', 'median', 'mode', 
                                          'minumum_absolute_value',
                                          'maximum_absolute_value') and                        
                        not lastcm.get_qualifier('within', None) and 
                        not lastcm.get_qualifier('over', None)):
                        # It was a null collapse (i.e. the method is
                        # the same as the last one and the size of the
                        # collapsed axis hasn't changed).
                        cell_method = None
                        if within:
                            lastcm.within = within
                        elif over:
                            lastcm.over = over
        #--- End: if
    
        if cell_method is not None:
            self.set_construct(cell_method)

        if verbose:
            print('    Modified cell methods =', self.cell_methods.ordered()) # pragma: no cover


    def direction(self, identity, axes=None, **kwargs):
        '''Whether or not a domain axis is increasing.

    An domain axis is considered to be increasing if its dimension
    coordinate values are increasing in index space or if it has no
    dimension coordinate.
    
    .. seealso:: `directions`
    
    :Parameters:
    
        identity:
           Select the domain axis construct by one of:
    
              * An identity or key of a 1-d coordinate construct that
                whose data spans the domain axis construct.
    
              * A domain axis construct identity or key.
    
              * The position of the domain axis construct in the field
                construct's data.
    
            The *identity* parameter selects the domain axis as
            returned by this call of the field's `domain_axis` method:
            ``f.domain_axis(identity)``.
    
        axes: deprecated at version 3.0.0
            Use the *identity* parmeter instead.
    
        size:  deprecated at version 3.0.0
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `bool`
            Whether or not the domein axis is increasing.
            
    **Examples:**
    
    >>> print(f.dimension_coordinate('X').array)
    array([  0  30  60])
    >>> f.direction('X')
    True
    >>> g = f.flip('X')
    >>> g.direction('X')
    False

        '''
        if axes:
            _DEPRECATION_ERROR_KWARGS(self, 'direction', axes=True) # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'direction', kwargs) # pragma: no cover

        axis = self.domain_axis(identity, key=True, default=None)
        if axis is None:
            return True
        
        for key, coord in self.dimension_coordinates.items():            
            if axis == self.get_data_axes(key)[0]:
                return coord.direction()
        #--- End: for

        return True


    def directions(self):
        '''Return a dictionary mapping all domain axes to their directions.

    .. seealso:: `direction`
    
    :Returns:
    
        `dict`
            A dictionary whose key/value pairs are domain axis keys
            and their directions.
    
    **Examples:**
    
    >>> d.directions()
    {'dim1': True, 'dim0': False}

        '''        
        out = {key: True for key in self.domain_axes.keys()}
        
        for key, dc in self.dimension_coordinates.items():
            direction = dc.direction()
            if not direction:
                axis = self.get_data_axes(key)[0]
                out[axis] = dc.direction()
        #--- End: for
        
        return out


    def insert_dimension(self, axis, position=0, inplace=False):
        '''Insert a size 1 axis into the data array.

    .. versionadded:: 3.0.0
    
    .. seealso:: `domain_axis`, `flip`, `squeeze`, `transpose`,
                 `unsqueeze`
    
    :Parameters:
    
        axis:
            Select the domain axis to, defined by that which would be
            selected by passing the given axis description to a call
            of the field's `domain_axis` method. For example, for a
            value of ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.
    
        position: `int`, optional
            Specify the position that the new axis will have in the
            data array. By default the new axis has position 0, the
            slowest varying position.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
    :Returns:
    
        `Field`, or `None`
            The field construct with expanded data, or `None` of the
            operation was in-place.
    
    **Examples:**
    
    >>> g = f.insert_dimension('time')
    >>> g = f.insert_dimension('time', 2)
    >>> g = f.insert_dimension(1)
    >>> g = f.insert_dimension('domainaxis2', -1)
    >>> f.insert_dimension('Z', inplace=True)

        '''
        if inplace:
            f = self
        else:
            f = self.copy()
            
        axis = self.domain_axis(axis, key=True, default=ValueError(
            "Can't identify a unique axis to insert"))

        # Expand the dims in the field's data array
        super(Field, f).insert_dimension(axis=axis, position=position,
                                         inplace=True)

        if inplace:
            f = None
        return f


    def indices(self, *mode, **kwargs):
        '''Create indices based on domain metadata that define a subspace of
    the field.

    The subspace is defined in "domain space" via data array values of its
    domain items: dimension coordinate, auxiliary coordinate, cell
    measure, domain ancillary and field ancillary objects.
    
    If metadata items are not specified for an axis then a full slice
    (``slice(None)``) is assumed for that axis.
    
    Values for size 1 axes which are not spanned by the field's data array
    may be specified, but only indices for axes which span the field's
    data array will be returned.
    
    The conditions may be given in any order.
    
    .. seealso:: `where`, `subspace`
    
    :Parameters:
    
        mode: *optional*
    
            ==============  ==============================================
            *mode*           Description
            ==============  ==============================================
            ``'compress'``
    
            ``'envelope'``
    
            ``'full'``
            ==============  ==============================================
    
        kwargs: *optional*
            Keyword parameters identify items of the domain (such as a
            particular coordinate type) and its value sets conditions on
            their data arrays (e.g. the actual coordinate values). Indices
            are created which, for each axis, select where the conditions
            are met.
    
            A keyword name is a string which selects a unique item of the
            field. The string may be any string value allowed by the
            *description* parameter of the field's `item` method, which is
            used to select a unique domain item. See `cf.Field.item` for
            details.
            
              *Parameter example:*           
                The keyword ``lat`` will select the item returned by
                ``f.item('lat', role='dam')``. See the *exact* parameter.
    
            In general, a keyword value specifies a test on the selected
            item's data array which identifies axis elements. The returned
            indices for this axis are the positions of these elements.
    
              *Parameter example:*
                To create indices for the northern hemisphere, assuming
                that there is a coordinate with identity "latitude":
                ``f.indices(latitude=cf.ge(0))``
    
              *Parameter example:*
                To create indices for the northern hemisphere, identifying
                the latitude coordinate by its longtg name:
                ``f.indices(**{'long_name:latitude': cf.ge(0)})``. In this
                case it is necessary to use the ``**`` syntax because the
                ``:`` character is not allowed in keyword parameter names.
    
            If the value is a `slice` object then it is used as the axis
            indices, without testing the item's data array.
    
              *Parameter example:*
                To create indices for every even numbered element along
                the "Z" axis: ``f.indices(Z=slice(0, None, 2))``.
    
    
            **Multidimensional items**
              Indices based on items which span two or more axes are
              possible if the result is a single element index for each of
              the axes spanned. In addition, two or more items must be
              provided, each one spanning the same axes  (in any order).
    
                *Parameter example:*          
                  To create indices for the unique location 45 degrees
                  north, 30 degrees east when latitude and longitude are
                  stored in 2-dimensional auxiliary coordiantes:
                  ``f.indices(latitude=45, longitude=30)``. Note that this
                  example would also work if latitude and longitude were
                  stored in 1-dimensional dimensional or auxiliary
                  coordinates, but in this case the location would not
                  have to be unique.
    
    :Returns:
    
        `tuple`
            
    **Examples:**
    
    These examples use the following field, which includes a dimension
    coordinate object with no identity (``ncvar:model_level_number``)
    and which has a data array which doesn't span all of the domain
    axes:
    
    
    >>> print(f)
    eastward_wind field summary
    ---------------------------
    Data           : eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1
    Cell methods   : time: mean
    Axes           : time(3) = [1979-05-01 12:00:00, ..., 1979-05-03 12:00:00] gregorian
                   : air_pressure(5) = [850.0, ..., 50.0] hPa
                   : grid_longitude(106) = [-20.54, ..., 25.66] degrees
                   : grid_latitude(110) = [23.32, ..., -24.64] degrees
    Aux coords     : latitude(grid_latitude(110), grid_longitude(106)) = [[67.12, ..., 22.89]] degrees_N
                   : longitude(grid_latitude(110), grid_longitude(106)) = [[-45.98, ..., 35.29]] degrees_E
    Coord refs     : <CF CoordinateReference: rotated_latitude_longitude>
    
    
    >>> f.indices(lat=23.32, lon=-20.54)
    (slice(0, 3, 1), slice(0, 5, 1), slice(0, 1, 1), slice(0, 1, 1))
    
    >>> f.indices(grid_lat=slice(50, 2, -2), grid_lon=[0, 1, 3, 90]) 
    (slice(0, 3, 1), slice(0, 5, 1), slice(50, 2, -2), [0, 1, 3, 90])
    
    >>> f.indices(grid_lon=cf.wi(0, 10, 'degrees'), air_pressure=850)
    (slice(0, 3, 1), slice(0, 1, 1), slice(0, 110, 1), slice(47, 70, 1))
    
    >>> f.indices(grid_lon=cf.wi(0, 10), air_pressure=cf.eq(85000, 'Pa')
    (slice(0, 3, 1), slice(0, 1, 1), slice(0, 110, 1), slice(47, 70, 1))
    
    >>> f.indices(grid_long=cf.gt(0, attr='lower_bounds'))
    (slice(0, 3, 1), slice(0, 5, 1), slice(0, 110, 1), slice(48, 106, 1))

        '''
        if 'exact' in mode:
            _DEPRECATION_ERROR("'exact' mode has been deprecated and is no longer available. It is now assumed that, where applicable, keyword arguments not regular expressions. Use 're.compile' keywords for regular expressions.") # pragma: no cover
            
        envelope = 'envelope' in mode
        full     = 'full' in mode
        compress = 'compress' in mode or not (envelope or full)
        _debug   = '_debug' in mode

        if _debug:
            print('Field.indices:') # pragma: no cover
            print('    envelope, full, compress, _debug =', envelope, full, compress, _debug) # pragma: no cover

        auxiliary_mask = []
        
        data_axes = self.get_data_axes()

        # Initialize indices
        indices = [slice(None)] * self.ndim

        domain_axes = self.domain_axes
        constructs = self.constructs.filter_by_data()
        
        parsed = {}
        unique_axes = set()
        n_axes = 0
        for identity, value in kwargs.items():
            if identity in domain_axes:
                axes = (identity,)
                key = None
                construct = None
            else:
                c = constructs.filter_by_identity(identity)
                if len(c) != 1:
                    raise ValueError(
                        "Can't find indices: Ambiguous axis or axes: {!r}".format(identity)) # ooo
                            
                key, construct = dict(c).popitem()

                axes = self.get_data_axes(key)
            
            sorted_axes = tuple(sorted(axes))
            if sorted_axes not in parsed:
                n_axes += len(sorted_axes)

            parsed.setdefault(sorted_axes, []).append(
                (axes, key, construct, value))

            unique_axes.update(sorted_axes)
        #--- End: for

        if len(unique_axes) < n_axes:
            raise ValueError(
                "Can't find indices: Multiple constructs with incompatible domain axes")

        for sorted_axes, axes_key_construct_value in parsed.items():
            axes, keys, constructs, points = list(zip(*axes_key_construct_value))
            n_items = len(constructs)
            n_axes  = len(sorted_axes)

            if n_items > n_axes:
                if n_axes == 1:
                    a = 'axis'
                else:
                    a = 'axes'

                raise ValueError(
                    "Error: Can't specify {} conditions for {} {}: {}".format(
                        n_items, n_axes, a, points))
            
            create_mask = False

            item_axes = axes[0]

            if _debug:
                print('    item_axes =', repr(item_axes)) # pragma: no cover
                print('    keys      =', repr(keys)) # pragma: no cover
                
            if n_axes == 1:
                #-----------------------------------------------------
                # 1-d item
                #-----------------------------------------------------
                ind = None
                
                if _debug:
                    print('    {} 1-d constructs: {!r}'.format(n_items, constructs)) # pragma: no cover

                axis  = item_axes[0]
                item  = constructs[0]
                value = points[0]

                if _debug:
                    print('    axis      =', repr(axis)) # pragma: no cover
                    print('    value     =', repr(value)) # pragma: no cover

                if isinstance(value, (list, slice, tuple, numpy_ndarray)):
                    #-------------------------------------------------
                    # 1-dimensional CASE 1: Value is already an index,
                    #                       e.g. [0], (0,3),
                    #                       slice(0,4,2),
                    #                       numpy.array([2,4,7])
                    #-------------------------------------------------
                    if _debug:
                        print('    1-d CASE 1: ',) # pragma: no cover
                        
                    index = value
                    
#                    if envelope or full:
#                        raise ValueError(
#                            "Can't create 'full' nor 'envelope' indices from {!r}".format(value))
                    if envelope or full:
                        size = self.constructs[axis].get_size()
                        d = Data(list(range(size)))
                        ind = (d[value].array,)
                        index = slice(None)
                    
                elif (item is not None and
                      isinstance(value, Query) and 
                      value.operator in ('wi', 'wo') and
                      item.isdimension and
                      self.iscyclic(axis)):
  #                    self.iscyclic(sorted_axes)):
                    #-------------------------------------------------
                    # 1-dimensional CASE 2: Axis is cyclic and
                    #                       subspace criterion is a
                    #                       'within' or 'without'
                    #                       Query instance
                    #-------------------------------------------------
                    if _debug:
                        print('    1-d CASE 2: ',) # pragma: no cover

                    if item.increasing:
                        anchor0 = value.value[0]
                        anchor1 = value.value[1]
                    else:
                        anchor0 = value.value[1]
                        anchor1 = value.value[0]

                    a = self.anchor(axis, anchor0, dry_run=True)['roll']
                    b = self.flip(axis).anchor(axis, anchor1, dry_run=True)['roll']
                    
                    size = item.size 
                    if abs(anchor1 - anchor0) >= item.period():
                        if value.operator == 'wo':
                            start = 0
                            stop  = 0
                        else:
                            start = -a
                            stop  = -a
                    elif a + b == size:
                        b = self.anchor(axis, anchor1, dry_run=True)['roll']
                        if b == a:
                            if value.operator == 'wo':
                                start= -a
                                stop = -a
                            else:
                                start = 0
                                stop  = 0
                        else:
                            if value.operator == 'wo':
                                start= 0
                                stop = 0
                            else:
                                start = -a
                                stop  = -a
                    else:
                        if value.operator == 'wo':
                            start = b - size
                            stop  = -a + size
                        else:
                            start = -a
                            stop  = b - size
    
                    index = slice(start, stop, 1)

                    if full:
    #                    index = slice(start, start+size, 1)
                        d = Data(list(range(size)))
                        d.cyclic(0)
                        ind = (d[index].array,)

                        index = slice(None)                        
#                        ind = (numpy_arange((stop%size)-start, size),)

                elif item is not None:
                    #-------------------------------------------------
                    # 1-dimensional CASE 3: All other 1-d cases
                    #-------------------------------------------------
                    if _debug:
                        print('    1-d CASE 3:',) # pragma: no cover

                    item_match = (value == item)
                    
                    if not item_match.any():                        
                        raise IndexError(
                            "No {!r} axis indices found from: {}".format(identity, value))
                
                    index = numpy_asanyarray(item_match)
                    
                    if envelope or full:
                        if numpy_ma_isMA(index):
                            ind = numpy_ma_where(index)
                        else:
                            ind = numpy_where(index)

                        index = slice(None)

                else:
                    raise ValueError("Must specify a domain axis construct or a construct with data for which to create indices")

                if _debug:
                    print('    index =', index) # pragma: no cover
                   
                # Put the index into the correct place in the list of
                # indices.
                #
                # Note that we might overwrite it later if there's an
                # auxiliary mask for this axis.
                if axis in data_axes:
                    indices[data_axes.index(axis)] = index
                                    
            else:
                #-----------------------------------------------------
                # N-dimensional constructs
                #-----------------------------------------------------
                if _debug:
                    print('    {} N-d constructs: {!r}'.format(n_items, constructs)) # pragma: no cover
                    print('    {} points        : {!r}'.format(len(points), points)) # pragma: no cover
                    print('    field.shape     :', self.shape) # pragma: no cover
                
                # Make sure that each N-d item has the same relative
                # axis order as the field's data array.
                #
                # For example, if the data array of the field is
                # ordered T Z Y X and the item is ordered Y T then the
                # item is transposed so that it is ordered T Y. For
                # example, if the field's data array is ordered Z Y X
                # and the item is ordered X Y T (T is size 1) then
                # tranpose the item so that it is ordered Y X T.
                g = self.transpose(data_axes, constructs=True)

#                g = self
#                data_axes = .get_data_axes(default=None)
#                for item_axes2 in axes:
#                    if item_axes2 != data_axes:
#                        g = self.transpose(data_axes, constructs=True)
#                        break

                item_axes = g.get_data_axes(keys[0])

                constructs = [g.constructs[key] for key in keys]
                if _debug:
                    print('    transposed N-d constructs: {!r}'.format(constructs)) # pragma: no cover

                    
                item_matches = [(value == construct).data
                                for value, construct in zip(points, constructs)]

#                for z in item_matches:
#                    print ('Z=', repr(z.array))
                
                item_match = item_matches.pop()

                for m in item_matches:
                    item_match &= m
                    
                item_match = item_match.array  # LAMA alert

                if numpy_ma_isMA:                    
                    ind = numpy_ma_where(item_match)
                else:
                    ind = numpy_where(item_match)
                    
                if _debug:
                    print('    item_match  =', item_match) # pragma: no cover
                    print('    ind         =', ind) # pragma: no cover

                bounds = [item.bounds.array[ind] for item in constructs
                          if item.has_bounds()]

#                print ( 'bounds=', bounds)
                
                contains = False
                if bounds:
                    points2 = []
                    for v, construct in zip(points, constructs):  
                        if isinstance(v, Query):
                            if v.operator == 'contains':
                                contains = True
                                v = v.value
                            elif v.operator == 'eq':
                                v = v.value
                            else:
                                contains = False
                                break
                        #--- End: if

                        v = Data.asdata(v)
                        if v.Units:
                            v.Units = construct.Units
                        
                        points2.append(v.datum())
                    #--- End: for
                #--- End: if

                if contains:
                    # The coordinates have bounds and the condition is
                    # a 'contains' Query object. Check each
                    # potentially matching cell for actually including
                    # the point.
                    try:
                        Path
                    except NameError:
                        raise ImportError(
                            "Must install matplotlib to create indices based on a 'contains' Query object")
                    
                    if n_items != 2:
                        raise IndexError(
                            "Can't index for cell from {}-d coordinate objects".format(
                                n_axes))

                    if 0 < len(bounds) < n_items:
                        raise ValueError("bounds alskdaskds TODO")

                    # Remove grid cells if, upon closer inspection,
                    # they do actually contain the point.
#                    for i in zip(*zip(*bounds)):
#                        print (i)
                    delete = [n for n, vertices in enumerate(zip(*zip(*bounds)))
                              if not Path(zip(*vertices)).contains_point(points2)]
                    
                    if delete:
                        ind = [numpy_delete(ind_1d, delete) for ind_1d in ind]
                #--- End: if                
            #--- End: if

            if ind is not None:
                mask_shape = [None] * self.ndim
                masked_subspace_size = 1
                ind = numpy_array(ind)
                if _debug:
                    print('    ind =', ind) # pragma: no cover

                for i, (axis, start, stop) in enumerate(zip(item_axes,
                                                            ind.min(axis=1),
                                                            ind.max(axis=1))):
                    if axis not in data_axes:
                        continue

                    position = data_axes.index(axis)

                    if indices[position] == slice(None):
                        if compress:
                            # Create a compressed index for this axis
                            size = stop - start + 1
                            index = sorted(set(ind[i]))
                        elif envelope:
                            # Create an envelope index for this axis
                            stop += 1
                            size = stop - start
                            index = slice(start, stop)
                        elif full:
                            # Create a full index for this axis
                            start = 0
#                            stop = self.axis_size(axis)
                            stop = self.domain_axes[axis].get_size()
                            size = stop - start                        
                            index = slice(start, stop)
                        else:
                            raise ValueError("Must have full, envelope or compress") # pragma: no cover
                        
                        indices[position] = index

                    mask_shape[position] = size    
                    masked_subspace_size *= size
                    ind[i] -= start
                #--- End: for

                create_mask = ind.shape[1] < masked_subspace_size
            else:
                create_mask = False

            # --------------------------------------------------------
            # Create an auxiliary mask for these axes
            # --------------------------------------------------------
            if _debug:
                print('    create_mask =', create_mask) # pragma: no cover

            if create_mask:
                if _debug:
                    print('    mask_shape  = ', mask_shape) # pragma: no cover
                    
                mask = self.data._create_auxiliary_mask_component(mask_shape,
                                                                  ind, compress)
                auxiliary_mask.append(mask)
                if _debug:
                    print('    mask_shape  =', mask_shape) # pragma: no cover
                    print('    mask.shape  =', mask.shape) # pragma: no cover
        #--- End: for

        indices = tuple(parse_indices(self.shape, tuple(indices)))

        if auxiliary_mask:
            indices = ('mask', auxiliary_mask) + indices
        
        if _debug:
            print('\n    Final indices =', indices) # pragma: no cover

        # Return the tuple of indices and the auxiliary mask (which
        # may be None)
        return indices


    def set_data(self, data, axes=None, set_axes=True, copy=True):
        '''Set the field construct data.

    .. versionadded:: 3.0.0
    
    .. seealso:: `data`, `del_data`, `get_data`, `has_data`,
                 `set_construct`
    
    :Parameters:
    
        data: `Data`
            The data to be inserted.
    
        axes: (sequence of) `str` or `int`, optional
            Set the domain axes constructs that are spanned by the
            data. If unset, and the *set_axes* parameter is True, then
            an attempt will be made to assign existing domain axis
            constructs to the data.
    
            The contents of the *axes* parameter is mapped to domain
            axis contructs by translating each element into a domain
            axis construct key via the `domain_axis` method.
    
            *Parameter example:*
              ``axes='domainaxis1'``
            
            *Parameter example:*
              ``axes='X'``
            
            *Parameter example:*
              ``axes=['latitude']``
            
            *Parameter example:*
              ``axes=['X', 'longitude']``
            
            *Parameter example:*
              ``axes=[1, 0]``
    
        set_axes: `bool`, optional
            If `False` then do not set the domain axes constructs that
            are spanned by the data, even if the *axes* parameter has
            been set. By default the axes are set either according to
            the *axes* parameter, or an attempt will be made to assign
            existing domain axis constructs to the data.
    
        copy: `bool`, optional
            If `True` then set a copy of the data. By default the data
            are not copied.
       
    :Returns:
    
        `None`
    
    **Examples:**
    
    >>> f.axes()
    {'dim0': 1, 'dim1': 3}
    >>> f.insert_data(cf.Data([[0, 1, 2]]))
    
    >>> f.axes()
    {'dim0': 1, 'dim1': 3}
    >>> f.insert_data(cf.Data([[0, 1, 2]]), axes=['dim0', 'dim1'])
    
    >>> f.axes()
    {}
    >>> f.insert_data(cf.Data([[0, 1], [2, 3, 4]]))
    >>> f.axes()
    {'dim0': 2, 'dim1': 3}
    
    >>> f.insert_data(cf.Data(4))
    
    >>> f.insert_data(cf.Data(4), axes=[])
    
    >>> f.axes()
    {'dim0': 3, 'dim1': 2}
    >>> data = cf.Data([[0, 1], [2, 3, 4]])
    >>> f.insert_data(data, axes=['dim1', 'dim0'], copy=False)
    
    >>> f.insert_data(cf.Data([0, 1, 2]))
    >>> f.insert_data(cf.Data([3, 4, 5]), replace=False)
    ValueError: Can't initialize data: Data already exists
    >>> f.insert_data(cf.Data([3, 4, 5]))

        '''
        if not set_axes:
            super().set_data(data, axes=None, copy=copy)
            return
            
        if data.isscalar:
            # --------------------------------------------------------
            # The data array is scalar
            # --------------------------------------------------------
            if axes or axes == 0:
                raise ValueError(
                    "Can't set data: Wrong number of axes for scalar data array: axes={}".format(axes))
            
            axes = []

        elif axes is not None:
            # --------------------------------------------------------
            # Axes have been set
            # --------------------------------------------------------
            if isinstance(axes, (str, int, slice)):
                axes = (axes,)
                
            axes = [self.domain_axis(axis, key=True) for axis in axes]

            if len(axes) != data.ndim:
                raise ValueError(
                    "Can't set data: {} axes provided, but {} needed".format(
                        len(axes), data.ndim))

            domain_axes = self.domain_axes()
            for axis, size in zip(axes, data.shape):
                axis_size = domain_axes[axis].get_size(None)
                if size != axis_size:
                    axes_shape = tuple(domain_axes[axis].get_size(None) for axis in axes)
                    raise ValueError(
                        "Can't set data: Data shape {} differs from shape implied by axes {}: {}".format(
                            data.shape, axes, axes_shape))
            #--- End: for

        elif self.get_data_axes(default=None) is None:
            # --------------------------------------------------------
            # The data is not scalar and axes have not been set and
            # the domain does not have data axes defined
            #
            # => infer the axes
            # --------------------------------------------------------
            domain_axes = self.domain_axes
            if not domain_axes:
                raise ValueError(
                    "Can't set data: No domain axes exist")

            data_shape = data.shape
            if len(data_shape) != len(set(data_shape)):
                raise ValueError(
                    "Can't insert data: Ambiguous data shape: {}. Consider setting the axes parameter.".format(
                        data_shape))

            axes = []
            for n in data_shape:
                da = domain_axes.filter_by_size(n)
                if len(da) != 1:
                    raise ValueError(
                        "Can't insert data: Ambiguous data shape: {}. Consider setting the axes parameter.".format(
                            data_shape))
                
                axes.append(da.key())
                
        else:
            # --------------------------------------------------------
            # The data is not scalar and axes have not been set, but
            # there are data axes defined on the field.
            # --------------------------------------------------------
            axes = self.get_data_axes()
            if len(axes) != data.ndim:
                raise ValueError(
                    "Wrong number of axes for data array: {!r}".format(axes))
            
#            domain_axes = self.domain_axes
#            for n in data.shape:
#                da = domain_axes.filter_by_size(n)
#                if len(da) != 1:
#                    raise ValueError(
#                        "Can't insert data: Ambiguous data shape: {}. {} domain axes have size {}. Consider setting the axes parameter.".format(
#                            data.shape, len(da), n))
#            #--- End: for
            
            domain_axes = self.domain_axes
            for axis, size in zip(axes, data.shape):
                if domain_axes[axis].get_size(None) != size:
                    raise ValueError(
                        "Can't insert data: Incompatible size for axis {!r}: {}".format(axis, size))
                
#                try:
#                    self.set_construct(DomainAxis(size), key=axis, replace=False)
#                except ValueError:
#                    raise ValueError(
#"Can't insert data: Incompatible size for axis {!r}: {}".format(axis, size))
            #--- End: for
        #--- End: if

        super().set_data(data, axes=axes, copy=copy)


    def domain_mask(self, **kwargs):
        '''Return a boolean field that is True where criteria are met.

    .. versionadded:: 1.1
    
    .. seealso:: `indices`, `mask`, `subspace`
    
    :Parameters:
    
    
        kwargs: optional
    
    :Returns:
    
        `Field`
            The domain mask.
    
    **Examples:**
    
    Create a domain mask which is masked at all between between -30
    and 30 degrees of latitude:
    
    >>> m = f.domain_mask(latitude=cf.wi(-30, 30))

        '''
        mask = self.copy()

        mask.clear_properties()
        mask.nc_del_variable(None)

        for key in self.constructs.filter_by_type('cell_method', 'field_ancillary'):
            mask.del_construct(key)

        false_everywhere = Data.zeros(self.shape, dtype=bool)

        mask.set_data(false_everywhere, axes=self.get_data_axes(), copy=False)

        mask.subspace[mask.indices(**kwargs)] = True

        mask.long_name = 'domain mask'

        return mask


    def match_by_construct(self, *mode, **constructs):
        '''Whether or not metadata constructs satisfy conditions.

    .. versionadded:: 3.0.0
    
    .. seealso: `match`, `match_by_property`, `match_by_rank`,
                `match_by_identity`, `match_by_ncvar`,
                `match_by_units`
    
    :Parameters:
    
        mode: optional
            Define the behaviour when multiple conditions are provided.
    
            By default (or if the *mode* parameter is ``'and'``) the
            match is True if the field construct satisfies all of the
            given conditions, but if the *mode* parameter is ``'or'``
            then the match is True when at least one of the conditions
            is satisfied.
    
        constructs: optional
            Define conditions on metadata constructs.
    
            Metadata constructs are identified by the name of a
            keyword parameter. A keyword parameter name of, say,
            ``identity`` selects the metadata constructs as returned
            by this call of the `constructs` attribute:
            ``f.constructs(identity)``. See `cf.Field.constructs` for
            details.
    
            The keyword parameter value defines a condition to be
            applied to the selected metadata constructs, and is one
            of:
    
              * `None`
              * a scalar or `Query` object
    
            If the condition is `None` then the condition is one of
            existence and is satisfied if at least one metadata
            construct has been selected, regardless of their
            data. Otherwise the condition is satisfied if any element
            of the unique selected metadata construct's data equals
            the value.
    
            *Parameter example:*
              To see if the field construct has a unique 'X' metadata
              construct with any data values of 180: ``X=180``
    
            *Parameter example:*
              To see if the field construct has a unique 'latitude'
              metadata construct with any data values greater than 0:
              ``latitude=cf.lt(0)``.
    
            *Parameter example:*
              To see if the field construct has any 'Y' metadata
              constructs: ``Y=None``.
    
            *Parameter example:*
              To see if the the field construct has any 'Y' metadata
              constructs: ``Y=None``.
    
    :Returns:
    
        `bool`
            Whether or not the conditions are met.
    
    **Examples:**
    
    >>> f.match_by_construct(T=cf.contains(cf.dt('2019-01-01')))
    
    >>> f.match_by_construct(Z=None, Y=30)
    
    >>> f.match_by_construct(X=None, Y=None)
    
    >>> f.match_by_construct(**{'grid_mapping_name:rotated_latitude_longitude': None})

        '''
        _or = False
        if mode:
            if len(mode) > 1:
                raise ValueError("match_by_construct: Can provide at most one positional argument")
            
            x = mode[0]
            if x == 'or':
                _or = True
            elif x != 'and':
                raise ValueError(
                    "match_by_construct: Positional argument, if provided, must one of 'or', 'and'")
        #--- End: if

        if not constructs:
            return True

        ok = True
        for identity, condition in constructs.items():
            c = self.constructs(identity)
            if condition is None:
                ok = bool(c)
            elif len(c) != 1:
                ok = False
            else:                    
                ok = (condition == c.value())
                try:
                    ok = ok.any()
                except AttributeError:
                    pass
            #--- End: if
                
            if _or:
                if ok:
                    break
            elif not ok:
                break
        #--- End: for

        return ok
    

    def match_by_rank(self, *ranks):
        '''Whether or not the number of domain axis constructs satisfy
    conditions.
    
    .. versionadded:: 3.0.0
    
    .. seealso: `match`, `match_by_property`, `match_by_construct`,
                `match_by_identity`, `match_by_ncvar`,
                `match_by_units`
    
    :Parameters:
    
        ranks: optional
            Define conditions on the number of domain axis constructs.
    
            A condition is one of:
    
              * `int`
              * a `Query` object
    
            The condition is satisfied if the number of domain axis
            constructs equals the condition value.
    
            *Parameter example:*
              To see if the field construct has 4 domain axis
              constructs: ``4``
    
            *Parameter example:*
              To see if the field construct has at least 3 domain axis
              constructs: ``cf.ge(3)``
    
    :Returns:
    
        `bool`
            Whether or not at least one of the conditions are met.
    
    **Examples:**
    
    >>> f.match_by_rank(3, 4)
    
    >>> f.match_by_rank(cf.wi(2, 4))
    
    >>> f.match_by_rank(1, cf.gt(3))

        '''
        if not ranks:
            return True

        n_domain_axes = len(self.domain_axes)        
        for rank in ranks:
            ok = (rank == n_domain_axes)
            if ok:
                return True
        #--- End: for

        return False


    def convolution_filter(self, weights, axis=None, mode=None,
                           cval=None, origin=0, update_bounds=True,
                           inplace=False, i=False):
        '''Return the field convolved along the given axis with the specified
    filter.
    
    Can be used to create running means.
    
    .. seealso:: `derivative`, `cf.relative_vorticity`

    :Parameters:
    
        weights: sequence of numbers
            Specify the window of weights to use for the filter.
    
            *Parameter example:*
              An unweighted 5-point moving average can be computed
              with ``weights=[0.2, 0.2, 0.2, 0.2, 02]``
    
            Note that the `scipy.signal.windows` package has suite of
            window functions for creating weights for filtering.
    
        axis:
            Select the domain axis over which the filter is to be
            applied, defined by that which would be selected by
            passing the given axis description to a call of the
            field's `domain_axis` method. For example, for a value of
            ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.
                
        mode: `str`, optional
            The *mode* parameter determines how the input array is
            extended when the filter overlaps a border. The default
            value is ``'constant'`` or, if the dimension being
            convolved is cyclic (as ascertained by the `iscyclic`
            method), ``'wrap'``. The valid values and their behaviour
            is as follows:
    
            ==============  ====================================  =================================
            *mode*          Description                           Behaviour
            ==============  ====================================  =================================
            ``'reflect'``   The input is extended by reflecting   ``(d c b a | a b c d | d c b a)``
                            about the edge                        
                                                                  
            ``'constant'``  The input is extended by filling      ``(k k k k | a b c d | k k k k)``
                            all values beyond the edge with       
                            the same constant value, defined      
                            by the *cval* parameter.              
                                                                  
            ``'nearest'``   The input is extended by              ``(a a a a | a b c d | d d d d)``
                            replicating the last point.           
                                                                  
            ``'mirror'``    The input is extended by reflecting     ``(d c b | a b c d | c b a)``
                            about the center of the last point.   
                                                                  
            ``'wrap'``      The input is extended by wrapping     ``(a b c d | a b c d | a b c d)``
                            around to the opposite edge.
            ==============  ====================================  =================================
    
            The position of the window can be changed by using the
            *origin* parameter.
    
        cval: scalar, optional
            Value to fill past the edges of the array if *mode* is
            ``'constant'``. Defaults to `None`, in which case the
            edges of the array will be filled with missing data.
    
            *Parameter example:*
               To extend the input by filling all values beyond the
               edge with zero: ``cval=0``
    
        origin: `int`, optional
            Controls the placement of the filter. Defaults to 0, which
            is the centre of the window. If the window has an even
            number weights then then a value of 0 defines the index
            defined by ``width/2 -1``.
    
            *Parameter example:*
              For a weighted moving average computed with a weights
              window of ``[0.1, 0.15, 0.5, 0.15, 0.1]``, if
              ``origin=0`` then the average is centred on each
              point. If ``origin=-2`` then the average is shifted to
              inclued the previous four points. If ``origin=1`` then
              the average is shifted to include the previous point and
              the and the next three points.
    
        update_bounds: `bool`, optional
            If `False` then the bounds of a dimension coordinate
            construct that spans the convolved axis are not
            altered. By default, the bounds of a dimension coordinate
            construct that spans the convolved axis are updated to
            reflect the width and origin of the window.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'convolution_filter', i=True) # pragma: no cover

        if isinstance(weights, str):
            _DEPRECATION_ERROR("A string-valued 'weights' parameter  has been deprecated at version 3.0.0 and is no longer available. Provide a sequence of numerical weights instead.") # pragma: no cover

        if isinstance(weights[0], str):
            _DEPRECATION_ERROR("A string-valued 'weights' parameter element has been deprecated at version 3.0.0 and is no longer available. Provide a sequence of numerical weights instead.") # pragma: no cover

        try:
            get_window
            convolve1d
        except NameError:
            raise ImportError(
                "Must install scipy to use the Field.convolution_filter method.")
                
        # Retrieve the axis
        axis_key = self.domain_axis(axis, key=True)
        if axis_key is None:
            raise ValueError('Invalid axis specifier: {!r}'.format(axis))

        # Default mode to 'wrap' if the axis is cyclic
        if mode is None:
            if self.iscyclic(axis_key):
                mode = 'wrap'
            else:
                mode = 'constant'
        #--- End: if

        # Get the axis index
        axis_index = self.get_data_axes().index(axis_key)

        # Section the data into sections up to a chunk in size
        sections = self.data.section([axis_index], chunks=True)

        # Set cval to NaN if it is currently None, so that the edges
        # will be filled with missing data if the mode is 'constant'
        if cval is None:
            cval = numpy_nan

        # Filter each section replacing masked points with numpy
        # NaNs and then remasking after filtering.
        for k in sections:
            input_array = sections[k].array
            masked = numpy_ma_is_masked(input_array)
            if masked:
                input_array = input_array.filled(numpy_nan)

            output_array = convolve1d(input_array, weights, axis=axis_index,
                                      mode=mode, cval=cval, origin=origin)
            if masked or (mode == 'constant' and numpy_isnan(cval)):
                with numpy_errstate(invalid='ignore'):
                    output_array = numpy_ma_masked_invalid(output_array)
           #--- End: if
            
            sections[k] = Data(output_array, units=self.Units)
        #--- End: for

        # Glue the sections back together again
        new_data = Data.reconstruct_sectioned_data(sections)

        # Construct new field
        if inplace:
            f = self
        else:
            f = self.copy()

        # Insert filtered data into new field
        f.set_data(new_data, axes=self.get_data_axes(), copy=False)

        # Update the bounds of the convolution axis if necessary
        if update_bounds:
            coord = f.dimension_coordinate(axis_key, default=None)
            if coord is not None and coord.has_bounds():
                old_bounds = coord.bounds.array
                length = old_bounds.shape[0]
                new_bounds = numpy_empty((length, 2))
                len_weights = len(weights)
                lower_offset = len_weights//2 + origin
                upper_offset = len_weights - 1 - lower_offset
                if mode == 'wrap':
                    if coord.direction():
                        new_bounds[:, 0] = coord.roll(0,  upper_offset).bounds.array[:, 0]
                        new_bounds[:, 1] = coord.roll(0, -lower_offset).bounds.array[:, 1] + coord.period()
                    else:
                        new_bounds[:, 0] = coord.roll(0,  upper_offset).bounds.array[:, 0] + 2*coord.period()
                        new_bounds[:, 1] = coord.roll(0, -lower_offset).bounds.array[:, 1] + coord.period()
                else:
                    new_bounds[upper_offset:length, 0] = old_bounds[0:length - upper_offset, 0]
                    new_bounds[0:upper_offset, 0] = old_bounds[0, 0]
                    new_bounds[0:length - lower_offset, 1] = old_bounds[lower_offset:length, 1]
                    new_bounds[length - lower_offset:length, 1] = old_bounds[length - 1, 1]

                coord.set_bounds(Bounds(data=Data(new_bounds, units=coord.Units)))
        #--- End: if

        if inplace:
            f = None
        return f


    def convert(self, identity, full_domain=True):
        '''Convert a metadata construct into a new field construct.

    The new field construct has the properties and data of the
    metadata construct, and domain axis constructs corresponding to
    the data. By default it also contains other metadata constructs
    (such as dimension coordinate and coordinate reference constructs)
    that define its domain.
    
    The cf.read function allows a field construct to be derived
    directly from a netCDF variable that corresponds to a metadata
    construct. In this case, the new field construct will have a
    domain limited to that which can be inferred from the
    corresponding netCDF variable - typically only domain axis and
    dimension coordinate constructs. This will usually result in a
    different field construct to that created with the convert method.
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `cf.read`
    	
    :Parameters:
    
        identity:
            Select the metadata construct by one of:
    
              * The identity or key of a construct.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); or a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='measure:area'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Longitude'``
    
            *Parameter example:*
              ``identity='domainancillary2'``
    
            *Parameter example:*
              ``identity='ncvar%areacello'``
    
        full_domain: `bool`, optional
            If `False` then do not create a domain, other than domain
            axis constructs, for the new field construct. By default
            as much of the domain as possible is copied to the new
            field construct.
    
    :Returns:	
    
        `Field`
            The new field construct.
    
    **Examples:**
    
    TODO

        '''
        key = self.construct_key(identity, default=None)
        if key is None:
            raise ValueError("Can't find metadata construct with identity {!r}".format(
                identity))

        return super().convert(key, full_domain=full_domain)


    def flip(self, axes=None, inplace=False, i=False, **kwargs):
        '''Flip (reverse the direction of) axes of the field.

    .. seealso:: `domain_axis`, `insert_dimension`, `squeeze`,
                 `transpose`, `unsqueeze`
    
    :Parameters:
    
        axes: (sequence of) `str` or `int`, optional
            Select the domain axes to flip, defined by the domain axes
            that would be selected by passing the each given axis
            description to a call of the field's `domain_axis`
            method. For example, for a value of ``'X'``, the domain
            axis construct returned by ``f.domain_axis('X'))`` is
            selected.

            If no axes are provided then all axes are flipped.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Field` or `None`
            The field construct with flipped axes, or `None` if the
            operation was in-place.
    
    **Examples:**
    
    >>> g = f.flip()
    >>> g = f.flip('time')
    >>> g = f.flip(1)
    >>> g = f.flip(['time', 1, 'dim2'])
    >>> f.flip(['dim2'], inplace=True)

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'flip', i=True) # pragma: no cover
            
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'flip', kwargs) # pragma: no cover

        if axes is None and not kwargs:
            # Flip all the axes
            axes = set(self.get_data_axes(default=()))
            iaxes = list(range(self.ndim))
        else:
            if isinstance(axes, (str, int)):
                 axes = (axes,)
                
            axes = set([self.domain_axis(axis, key=True) for axis in axes])

            data_axes = self.get_data_axes(default=())
            iaxes = [data_axes.index(axis) for axis in
                     axes.intersection(self.get_data_axes())]

        # Flip the requested axes in the field's data array
        f = super().flip(iaxes, inplace=inplace)
        if f is None:
            f = self
            
        # Flip any constructs which span the flipped axes
        for key, construct in f.constructs.filter_by_data().items():
            construct_axes = f.get_data_axes(key)
            construct_flip_axes = axes.intersection(construct_axes)
            if construct_flip_axes:
                iaxes = [construct_axes.index(axis) for axis in construct_flip_axes]
                construct.flip(iaxes, inplace=True)
        #--- End: for

        if inplace:
            f = None
        return f


    def anchor(self, axis, value, inplace=False, dry_run=False,
               i=False, **kwargs):
        '''Roll a cyclic axis so that the given value lies in the first
    coordinate cell.
    
    A unique axis is selected with the *axes* and *kwargs* parameters.
    
    .. versionadded:: 1.0
    
    .. seealso:: `axis`, `cyclic`, `iscyclic`, `period`, `roll`
    
    :Parameters:
    
        axis:
            The cyclic axis to be rolled, defined by that which would
            be selected by passing the given axis description to a
            call of the field's `domain_axis` method. For example, for
            a value of ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.

        value:
            Anchor the dimension coordinate values for the selected
            cyclic axis to the *value*. May be any numeric scalar
            object that can be converted to a `Data` object (which
            includes `numpy` and `Data` objects). If *value* has units
            then they must be compatible with those of the dimension
            coordinates, otherwise it is assumed to have the same
            units as the dimension coordinates. The coordinate values
            are transformed so that *value* is "equal to or just
            before" the new first coordinate value. More specifically:
            
              * Increasing dimension coordinates with positive period,
                P, are transformed so that *value* lies in the
                half-open range (L-P, F], where F and L are the
                transformed first and last coordinate values,
                respectively.

        ..

              * Decreasing dimension coordinates with positive period,
                P, are transformed so that *value* lies in the
                half-open range (L+P, F], where F and L are the
                transformed first and last coordinate values,
                respectively.

            *Parameter example:*
              If the original dimension coordinates are ``0, 5, ...,
              355`` (evenly spaced) and the period is ``360`` then
              ``value=0`` implies transformed coordinates of ``0, 5,
              ..., 355``; ``value=-12`` implies transformed
              coordinates of ``-10, -5, ..., 345``; ``value=380``
              implies transformed coordinates of ``380, 385, ...,
              715``.
    
            *Parameter example:*
              If the original dimension coordinates are ``355, 350,
              ..., 0`` (evenly spaced) and the period is ``360`` then
              ``value=355`` implies transformed coordinates of ``355,
              350, ..., 0``; ``value=0`` implies transformed
              coordinates of ``0, -5, ..., -355``; ``value=392``
              implies transformed coordinates of ``390, 385, ...,
              30``.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        dry_run: `bool`, optional
            Return a dictionary of parameters which describe the
            anchoring process. The field is not changed, even if *i*
            is True.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Field`        
            The rolled field.
    
    **Examples:**
    
    >>> f.iscyclic('X')
    True
    >>> f.dimension_coordinate('X').data
    <CF Data(8): [0, ..., 315] degrees_east> TODO
    >>> print(f.dimension_coordinate('X').array)
    [  0  45  90 135 180 225 270 315]
    >>> g = f.anchor('X', 230)
    >>> print(g.dimension_coordinate('X').array)
    [270 315   0  45  90 135 180 225]
    >>> g = f.anchor('X', cf.Data(590, 'degreesE'))
    >>> print(g.dimension_coordinate('X').array)
    [630 675 360 405 450 495 540 585]
    >>> g = f.anchor('X', cf.Data(-490, 'degreesE'))
    >>> print(g.dimension_coordinate('X').array)
    [-450 -405 -720 -675 -630 -585 -540 -495]
    
    >>> f.iscyclic('X')
    True
    >>> f.dimension_coordinate('X').data
    <CF Data(8): [0.0, ..., 357.1875] degrees_east>
    >>> f.anchor('X', 10000).dimension_coordinate('X').data
    <CF Data(8): [10001.25, ..., 10358.4375] degrees_east>
    >>> d = f.anchor('X', 10000, dry_run=True)
    >>> d
    {'axis': 'domainaxis2',
     'nperiod': <CF Data(1): [10080.0] 0.0174532925199433 rad>,
     'roll': 28}
    >>> (f.roll(d['axis'], d['roll']).dimension_coordinate(d['axis']) + d['nperiod']).data
    <CF Data(8): [10001.25, ..., 10358.4375] degrees_east>

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'anchor', i=True) # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'anchor', kwargs) # pragma: no cover

        axis = self.domain_axis(axis, key=True)

        if inplace or dry_run:
            f = self
        else:
            f = self.copy()
        
        dim = f.dimension_coordinates.filter_by_axis('and', axis).value(default=None)
        if dim is None:
            raise ValueError(
                "Can't shift non-cyclic {!r} axis".format(f.constructs.domain_axis_identity(axis)))

        period = dim.period()
        if period is None:
            raise ValueError("Cyclic {!r} axis has no period".format(dim.identity()))

        value = Data.asdata(value)
        if not value.Units:
            value = value.override_units(dim.Units)
        elif not value.Units.equivalent(dim.Units):
            raise ValueError(
                "Anchor value has incompatible units: {!r}".format(value.Units))

#        axis_size = f.axis_size(axis)
        axis_size = f.domain_axes[axis].get_size()
        if axis_size <= 1:
            # Don't need to roll a size one axis
            if dry_run:
                return {'axis': axis, 'roll': 0, 'nperiod': 0}
            else:
                if inplace:
                    f = None
                return f
        #-- End: if

        c = dim.get_data()

        if dim.increasing:
            # Adjust value so it's in the range [c[0], c[0]+period) 
            n = ((c[0] - value) / period).ceil()
            value1 = value + n * period

            shift = axis_size - numpy_argmax((c - value1 >= 0).array)
            if not dry_run:
                f.roll(axis, shift, inplace=True)     

            dim = f.dimension_coordinates.filter_by_axis('and', axis).value()
            #        dim = f.item(axis)
            n = ((value - dim.data[0]) / period).ceil()
        else:
            # Adjust value so it's in the range (c[0]-period, c[0]]
            n = ((c[0] - value) / period).floor()
            value1 = value + n * period

            shift = axis_size - numpy_argmax((value1 - c >= 0).array)

            if not dry_run:
                f.roll(axis, shift, inplace=True)     

            dim = f.dimension_coordinate(axis)
#            dim = f.dimension_coordinates.filter_by_axis('and', axis).value()
            #dim = f.item(axis)
            n = ((value - dim.data[0]) / period).floor()
        #--- End: if

        if dry_run:
            return  {'axis': axis, 'roll': shift, 'nperiod': n*period}

        if n:
            np = n * period
            dim += np
            bounds = dim.get_bounds(None)
            if bounds is not None:
                bounds += np
        #--- End: if

        if inplace:
            f = None
        return f


#    def argmax(self, axes=None, **kwargs):
#        '''DCH
#
#.. seealso:: `argmin`, `where`
#
#:Parameters:
#
#:Returns:
#
#    `Field`
#        TODO
#
#**Examples:**
#
#>>> g = f.argmax('T')
#
#        '''
#        if axes is None and not kwargs:
#            if self.ndim == 1:
#                pass
#            elif not self.ndim:
#                return
#
#        else:
#            axis = self.axis(axes, key=True, **kwargs)
#            if axis is None:
#                raise ValueError("Can't identify a unique axis")
#            elif self.axis_size(axis) != 1:
#                raise ValueError(
#"Can't insert an axis of size {0}: {0!r}".format(self.axis_size(axis), axis))
#            elif axis in self.get_data_axes():
#                raise ValueError(
#                    "Can't insert a duplicate axis: %r" % axis)
#        #--- End: if
#
#        f = self.copy(_omit_Data=True)
#
#        f.data = self.data.argmax(iaxis)
#
#        f.remove_axes(axis)
#
#        standard_name = f.get_property('standard_name', None)
#        long_name = f.get_property('long_name', standard_name)
#        
#        if standard_name is not None:
#            del f.standard_name
#
#        f.long_name = 'Index of first maximum'
#        if long_name is not None:
#            f.long_name += ' '+long_name
#
#        return f
#    #--- End: def

    # 1
    def autocyclic(self):
        '''Set dimensions to be cyclic.

A dimension is set to be cyclic if it has a unique longitude (or grid
longitude) dimension coordinate construct with bounds and the first
and last bounds values differ by 360 degrees (or an equivalent amount
in other units).
   
.. versionadded:: 1.0

.. seealso:: `cyclic`, `iscyclic`, `period`

:Returns:

   `None`

**Examples:**

>>> f.autocyclic()

        '''
        dims = self.dimension_coordinates('X')

        if len(dims) != 1:
            return

        key, dim = dict(dims).popitem()

        if not dim.Units.islongitude:
            if dim.get_property('standard_name', None) not in ('longitude', 'grid_longitude'):
                self.cyclic(key, iscyclic=False)
                return

        bounds = dim.get_bounds(None)
        if bounds is None:
            self.cyclic(key, iscyclic=False)
            return

        bounds_data = bounds.get_data(None)
        if bounds_data is None:
            self.cyclic(key, iscyclic=False)
            return 

        bounds = bounds_data.array
        
        period = Data(360.0, units='degrees')

        period.Units = bounds_data.Units

        if abs(bounds[-1, -1] - bounds[0, 0]) != period.array:
            self.cyclic(key, iscyclic=False)
            return

        self.cyclic(key, iscyclic=True, period=period)
    #--- End: def

    def axes(self, axes=None, **kwargs):
        '''Return domain axis constructs.

    .. seealso:: `constructs`, `domain_axis`, `domain_axes`

    :Parameters:

        axes:

        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Constructs`
            The domain axis constructs and their construct keys.
    
    **Examples:**
    
    >>> f.axes()
    Constructs:
    {}
    
    >>> f.axes()
    Constructs:
    {'domainaxis0': <DomainAxis: size(1)>,
     'domainaxis1': <DomainAxis: size(10)>,
     'domainaxis2': <DomainAxis: size(9)>,
     'domainaxis3': <DomainAxis: size(1)>}

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'axes', kwargs,
                "Use methods of the 'domain_axes' attribute instead.") # pragma: no cover

        if axes is None:
             return self.domain_axes
                
        if isinstance(axes, (str, int)):
            axes = (axes,)

        out = [self.domain_axis(identity, key=True, default=None)
               for identity in axes]

        out = set(out)
        out.discard(None)
            
        return self.domain_axes.filter_by_key(*out)
    

    def squeeze(self, axes=None, inplace=False, i=False, **kwargs):
        '''Remove size-1 axes from the data array.

    By default all size 1 axes are removed, but particular size 1 axes
    may be selected for removal.
    
    Squeezed domain axis constructs are not removed from the metadata
    contructs, nor from the domain.
    
    .. seealso:: `domain_axis`, `insert_dimension`, `flip`,
                 `remove_axes`, `transpose`, `unsqueeze`
    
    :Parameters:
    
        axes: (sequence of) `str` or `int`, optional
            Select the domain axes to squeeze, defined by the domain
            axes that would be selected by passing the each given axis
            description to a call of the field's `domain_axis`
            method. For example, for a value of ``'X'``, the domain
            axis construct returned by ``f.domain_axis('X'))`` is
            selected.

            If no axes are provided then all size-1 axes are squeezed.

        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Field` or `None`
            The field construct with squeezed data, or `None` of the
            operation was in-place.
    
            **Examples:**
    
    >>> g = f.squeeze()
    >>> g = f.squeeze('time')
    >>> g = f.squeeze(1)
    >>> g = f.squeeze(['time', 1, 'dim2'])
    >>> f.squeeze(['dim2'], inplace=True)

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'squeeze', i=True) # pragma: no cover
             
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'squeeze', kwargs) # pragma: no cover

        data_axes = self.get_data_axes()

        if axes is None and not kwargs:
            all_axes = self.domain_axes
            axes = [axis for axis in data_axes if all_axes[axis].get_size(None) == 1]
        else:
            if isinstance(axes, (str, int)):
                axes = (axes,)

            axes = [self.domain_axis(x, key=True) for x in axes]
            axes = set(axes).intersection(data_axes)

        iaxes = [data_axes.index(axis) for axis in axes]      

        # Squeeze the field's data array
        return super().squeeze(iaxes, inplace=inplace)

    
    def transpose(self, axes=None, constructs=False, inplace=False,
                  items=True, i=False, **kwargs):
        '''Permute the axes of the data array.

    By default the order of the axes is reversed, but any ordering may
    be specified by selecting the axes of the output in the required
    order.
    
    By default metadata constructs are not tranposed, but they may be
    if the *constructs* parmeter is set.
    
    .. seealso:: `domain_axis`, `insert_dimension`, `flip`, `squeeze`,
                 `unsqueeze`
    
    :Parameters:

        axes: (sequence of) `str` or `int`, optional
            Select the domain axis order, defined by the domain axes
            that would be selected by passing the each given axis
            description to a call of the field's `domain_axis`
            method. For example, for a value of ``'X'``, the domain
            axis construct returned by ``f.domain_axis('X'))`` is
            selected.

            Each dimension of the field construct's data must be
            provided, or if no axes are specified then the axis order
            is reversed.
   
        constructs: `bool`
            If `True` then metadata constructs are also transposed so
            that their axes are in the same relative order as in the
            tranposed data array of the field. By default metadata
            constructs are not altered.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        items: deprecated at version 3.0.0
            Use the *constructs* parameter instead.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Field` or `None`
            The field construct with transposed data, or `None` of the
            operation was in-place.
    
    **Examples:**
    
    >>> f.ndim
    3
    >>> g = f.transpose()
    >>> g = f.transpose(['time', 1, 'dim2'])
    >>> f.transpose(['time', -2, 'dim2'], inplace=True)

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'transpose', i=True) # pragma: no cover
             
        if not items:
            _DEPRECATION_ERROR_KWARGS(self, 'transpose', {'items': items},
                                      "Use keyword 'constructs' instead.") # pragma: no cover
            
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'transpose', kwargs) # pragma: no cover

        if axes is None:
            iaxes = list(range(self.ndim-1, -1, -1))
        else:
            data_axes = self.get_data_axes(default=())
            if isinstance(axes, (str, int)):
                axes = (axes,)
            axes2 = [self.domain_axis(x, key=True) for x in axes]
            if sorted(axes2) != sorted(data_axes):
                raise ValueError(
                    "Can't transpose {}: Bad axis specification: {!r}".format(
                        self.__class__.__name__, axes))

            iaxes = [data_axes.index(axis) for axis in axes2]
            
        # Transpose the field's data array
        return super().transpose(iaxes, constructs=constructs,
                                 inplace=inplace)
    #--- End: def

    # 1
    def unsqueeze(self, inplace=False, i=False, axes=None, **kwargs):
        '''Insert size 1 axes into the data array.

All size 1 domain axes which are not spanned by the field's data array
are inserted.

The axes are inserted into the slowest varying data array positions.

.. seealso:: `flip`, `insert_dimension`, `squeeze`, `transpose`

:Parameters:

    inplace: `bool`, optional
        If `True` then do the operation in-place and return `None`.

    i: deprecated at version 3.0.0
        Use the *inplace* parameter instead.

    axes: deprecated at version 3.0.0

    kwargs: deprecated at version 3.0.0

:Returns:

    `Field` or `None`
        The field construct with size-1 axes inserted in its data, or
        `None` of the operation was in-place.

**Examples:**

>>> g = f.unsqueeze()
>>> f.unsqueeze(['dim2'], inplace=True)

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'unsqueeze', i=True) # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'unsqueeze', kwargs) # pragma: no cover

        if axes is not None:
            _DEPRECATION_ERROR_KWARGS(
                self, 'unsqueeze', {'axes': axes},
                "All size one domain axes missing from the data are inserted. Use method 'insert_dimension' to insert an individual size one domain axis.") # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'unsqueeze', kwargs) # pragma: no cover

        if inplace:
            f = self
        else:
            f = self.copy()

        size_1_axes = self.domain_axes.filter_by_size(1)
        for axis in set(size_1_axes).difference(self.get_data_axes()):
            f.insert_dimension(axis, position=0, inplace=True)

        if inplace:
            f = None
        return f
    #--- End: def

    # 1
    def auxiliary_coordinate(self, identity, default=ValueError(),
                             key=False):
        '''Return an auxiliary coordinate construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the auxiliary coordinate construct by one of:
    
              * The identity or key of an auxiliary coordinate
                construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a unique 1-d auxiliary coordinate
                construct's data.
    
              * The position, in the field construct's data, of a
                domain axis construct that is spanned by a unique 1-d
                auxiliary coordinate construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); a `Query` object
            (e.g. ``cf.eq('longitude')``); or a compiled regular
            expression (e.g. ``re.compile('^atmosphere')``) that
            selects the relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'auxiliarycoordinate2'`` and
            ``'key%auxiliarycoordinate2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='auxiliarycoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
            *Parameter example:*
              ``identity=0``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `AuxiliaryCoordinate` or `str`
            The selected auxiliary coordinate construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        c = self.auxiliary_coordinates(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.auxiliary_coordinates.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def construct(self, identity, default=ValueError(), key=False):
        '''Select a metadata construct by its identity.

    TODO
        '''
        c = self.constructs.filter_by_identity(identity)
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def domain_ancillary(self, identity, default=ValueError(),
                         key=False):
        '''Return a domain ancillary construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the domain ancillary construct by one of:
    
              * The identity or key of a domain ancillary construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a unique 1-d domain ancillary construct's data.
    
              * The position, in the field construct's data, of a domain
                axis construct that is spanned by a unique 1-d domain
                ancillary construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); a `Query` object
            (e.g. ``cf.eq('longitude')``); or a compiled regular
            expression (e.g. ``re.compile('^atmosphere')``) that
            selects the relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'domainancillary2'`` and
            ``'key%domainancillary2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='domainancillary1'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity=0``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `DomainAncillary` or `str`
            The selected domain ancillary coordinate construct, or its
            key.
    
    **Examples:**
    
    TODO

        '''
        c = self.domain_ancillaries(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.domain_ancillaries.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def cell_measure(self, identity, default=ValueError(), key=False):
        '''Select a cell measure construct by its identity.

    New in version 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the cell measure construct by:
    
              * The identity or key of a cell measure construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a unique 1-d cell measure construct's data.
    
              * The position, in the field construct's data, of a
                domain axis construct that is spanned by a unique 1-d
                cell measure construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'long_name=Cell Area', ``'ncvar%areacello'``,
            etc.); a `Query` object (e.g. ``cf.eq('measure:area')``);
            or a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'cellmeasure2'`` and
            ``'key%cellmeasure2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='measure:area'``
    
            *Parameter example:*
              ``identity='cell_area'``
    
            *Parameter example:*
              ``identity='long_name=Cell Area'``
    
            *Parameter example:*
              ``identity='cellmeasure1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity=0``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `CellMeasure`or `str`
            The selected cell measure construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        c = self.cell_measures(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.cell_measures.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def cell_method(self, identity, default=ValueError(), key=False):
        '''Select a cell method construct by its identity.

    .. versionadadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the cell method construct by:
    
              * The identity or key of a cell method construct.
    
              * The identity or key of a domain axis construct that a
                unique cell method construct applies to.
    
              * The position, in the field construct's data, of a
                domain axis construct that a unique cell method
                construct applies to.
    
            A construct identity is specified by a string
            (e.g. ``'method:mean'``, etc.); a `Query` object
            (e.g. ``cf.eq('method:maximum')``); or a compiled regular
            expression (e.g. ``re.compile('^m')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``c`` has
            one identity:
    
               >>> c.identities()
               ['method:minimum']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'cellmethod2'`` and
            ``'key%cellmethod2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='method:variance'``
    
            *Parameter example:*
              ``identity='cellmethod1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity=0``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `CellMethod`or `str`
            The selected cell method construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        c = self.cell_methods(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            cm_keys = [key for key, cm in self.cell_methods.items()
                       if cm.get_axes(None) == (da_key,)]
            if cm_keys:
                c = self.cell_methods(*cm_keys)
            else:
                c = self.cell_methods(None)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def coordinate(self, identity, default=ValueError(), key=False):
        '''Return a dimension coordinate construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the dimension coordinate construct by one of:
    
              * The identity or key of a dimension coordinate
                construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a unique 1-d coordinate construct's data.
    
              * The position, in the field construct's data, of a
                domain axis construct that is spanned by a unique 1-d
                coordinate construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); a `Query` object
            (e.g. ``cf.eq('longitude')``); or a compiled regular
            expression (e.g. ``re.compile('^atmosphere')``) that
            selects the relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'auxiliarycoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='dimensioncoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional  
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `DimensionCoordinate` or `AuxiliaryCoordinate` or `str`
            The selected dimension or auxiliary coordinate construct,
            or its key.
    
    **Examples:**
    
    TODO

        '''
        c = self.coordinates(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.coordinates.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def coordinate_reference(self, identity, default=ValueError(),
                             key=False):
        '''Return a coordinate reference construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the coordinate reference construct by one of:
    
              * The identity or key of a coordinate reference
                construct.
    
            A construct identity is specified by a string
            (e.g. ``'grid_mapping_name:latitude_longitude'``,
            ``'latitude_longitude'``, ``'ncvar%lat_lon'``, etc.); a
            `Query` object (e.g. ``cf.eq('latitude_longitude')``); or
            a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            two identites:
    
               >>> x.identities()
               ['grid_mapping_name:latitude_longitude', 'ncvar%lat_lon']
    
            A identity's prefix of ``'grid_mapping_name:'`` or
            ``'standard_name:'`` may be omitted
            (e.g. ``'standard_name:atmosphere_hybrid_height_coordinate'``
            and ``'atmosphere_hybrid_height_coordinate'`` are both
            acceptable identities).
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'coordinatereference2'`` and
            ``'key%coordinatereference2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='standard_name:atmosphere_hybrid_height_coordinate'``
    
            *Parameter example:*
              ``identity='grid_mapping_name:rotated_latitude_longitude'``
    
            *Parameter example:*
              ``identity='transverse_mercator'``
    
            *Parameter example:*
              ``identity='coordinatereference1'``
    
            *Parameter example:*
              ``identity='key%coordinatereference1'``
    
            *Parameter example:*
              ``identity='ncvar%lat_lon'``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `CoordinateReference` or `str`
            The selected coordinate reference construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        coordinate_references = self.coordinate_references
        c = coordinate_references.filter_by_identity(identity)

        for cr_key, cr in coordinate_references.items():            
            if cr.match(identity):
                c._set_construct(cr, key=cr_key, copy=False)
        #--- End: for
                
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def field_ancillary(self, identity, default=ValueError(),
                        key=False):
        '''Return a field ancillary construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the field ancillary construct by one of:
    
              * The identity or key of an field ancillary construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a unique 1-d field ancillary construct's
                data.
    
              * The position, in the field construct's data, of a
                domain axis construct that is spanned by a unique 1-d
                field ancillary construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``, ``'ncvar%lat'``,
            etc.); a `Query` object (e.g. ``cf.eq('longitude')``); or
            a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'fieldancillary2'`` and
            ``'key%fieldancillary2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field construct's
            data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='fieldancillary1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
            *Parameter example:*
              ``identity=0``
    
        key: `bool`, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `FieldAncillary` or `str`
            The selected field ancillary coordinate construct, or its
            key.
    
    **Examples:**
    
    TODO

        '''
        c = self.field_ancillaries(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.field_ancillaries.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def dimension_coordinate(self, identity, key=False,
                             default=ValueError()):
        '''Return a dimension coordinate construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
            Select the dimension coordinate construct by one of:
    
              * The identity or key of a dimension coordinate
                construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a dimension coordinate construct's data.
    
              * The position, in the field construct's data, of a domain
                axis construct that is spanned by a dimension coordinate
                construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); a `Query` object
            (e.g. ``cf.eq('longitude')``); or a compiled regular
            expression (e.g. ``re.compile('^atmosphere')``) that
            selects the relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='dimensioncoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
        key: `bool, optional
            If `True` then return the selected construct key. By default
            the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `DimensionCoordinate` or `str`
            The selected dimension coordinate construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        c = self.dimension_coordinates(identity)
        if not c:
            da_key = self.domain_axis(identity, key=True, default=None)
            if da_key is not None:
                c = self.dimension_coordinates.filter_by_axis('exact', da_key)
        #-- End: if
        
        if key:
            return c.key(default=default)

        return c.value(default=default)


    def domain_axis(self, identity, key=False, default=ValueError()):
        '''Return a domain axis construct, or its key.

    .. versionadded:: 3.0.0
    
    .. seealso:: TODO
    
    :Parameters:
    
        identity:
           Select the domain axis construct by one of:
    
              * An identity or key of a 1-d coordinate construct that
                whose data spans the domain axis construct.
    
              * A domain axis construct identity or key.
    
              * The position of the domain axis construct in the field
                construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); or a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', 'T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
            
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='dimensioncoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='key%domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
            *Parameter example:*
              ``identity=2``
    
        key: `bool, optional
            If `True` then return the selected construct key. By
            default the construct itself is returned.
    
        default: optional
            Return the value of the *default* parameter if a construct
            can not be found. If set to an `Exception` instance then
            it will be raised instead.
    
    :Returns:
    
        `DomainAxis` or `str`
            The selected domain axis construct, or its key.
    
    **Examples:**
    
    TODO

        '''
        # Try for index
        try:
            da_key = self.get_data_axes(default=None)[identity]
        except TypeError:
            pass
        except IndexError:
            return self._default(
                default,
                "Index does not exist for field construct data dimenions")
        else:
            identity = da_key

        domain_axes = self.domain_axes(identity)
        if len(domain_axes) == 1:
            # identity is a unique domain axis construct identity
            da_key = domain_axes.key()
        else:
            # identity is not a unique domain axis construct identity
            da_key = self.domain_axis_key(identity, default=default)
            
        if key:
            return da_key

        return self.constructs[da_key]


    def axes_names(self, *identities, **kwargs):
        '''Return canonical identities for each domain axis construct.

    :Parameters:

        kwargs: deprecated at version 3.0.0

    :Returns:
    
        `dict`
            The canonical name for the domain axis construct.
    
    **Examples:**
    
    >>> f.axis_names()
    {'domainaxis0': 'atmosphere_hybrid_height_coordinate',
     'domainaxis1': 'grid_latitude',
     'domainaxis2': 'grid_longitude'}

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'axes_names', kwargs) # pragma: no cover

        out = dict(self.domain_axes)

        for key in tuple(out):
            value = self.constructs.domain_axis_identity(key)
            if value is not None:
                out[key] = value
            else:
                del out[key]
        #--- End: for

        return out


    def axis_size(self, identity, default=ValueError(), axes=None,
                  **kwargs):
        '''Return the size of a domain axis construct.

    :Parameters:
    
        identity:
           Select the domain axis construct by one of:
    
              * An identity or key of a 1-d coordinate construct that
                whose data spans the domain axis construct.
    
              * A domain axis construct identity or key.
    
              * The position of the domain axis construct in the field
                construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); or a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', 'T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            A position of a domain axis construct in the field
            construct's data is specified by an integer index.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
            
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='dimensioncoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='key%domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
    
            *Parameter example:*
              ``identity=2``
    
        default: optional
            Return the value of the *default* parameter if a domain
            axis construct can not be found. If set to an `Exception`
            instance then it will be raised instead.
    
        axes: deprecated at version 3.0.0
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
        
        `int`
            The size of the selected domain axis
    
    **Examples:**
    
    >>> f
    <CF Field: eastward_wind(time(3), air_pressure(5), latitude(110), longitude(106)) m s-1>
    >>> f.axis_size('longitude')
    106
    >>> f.axis_size('Z')
    5

        '''
        if axes:
            _DEPRECATION_ERROR_KWARGS(self, 'axis_size', axes=True) # pragma: no cover

        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'axis_size', kwargs, "See f.domain_axes") # pragma: no cover

        domain_axes = self.domain_axes

        da = domain_axes.get(axis)
        if da is not None:
            return da.get_size(default=default)
            
        key = self.domain_axis(axis, key=True, default=None)
        if key is None:
            return self.domain_axis(axis, key=True, default=default)

        return domain_axes[key].get_size(default=default)


    def set_construct(self, construct, key=None, axes=None,
                      set_axes=True, copy=True):
        '''Set a metadata construct.

    When inserting a construct with data, the domain axes constructs
    spanned by the data are either inferred, or specified with the
    *axes* parameter.

    For a dimension coordinate construct, an exisiting dimension
    coordinate construct is discarded if it spans the same domain axis
    construct (since only one dimension coordinate construct can be
    associated with a given domain axis construct).

    .. vesionadded:: 3.0.0
    
    .. seealso:: `constructs`, `del_construct`, `get_construct`,
                 `set_coordinate_reference`, `set_data_axes`
    
    :Parameters:
    
        construct:
            The metadata construct to be inserted.
    
        key: `str`, optional
            The construct identifier to be used for the construct. If
            not set then a new, unique identifier is created
            automatically. If the identifier already exisits then the
            exisiting construct will be replaced.
    
            *Parameter example:*
              ``key='cellmeasure0'``
    
        axes: (sequence of) `str` or `int`, optional
            Set the domain axes constructs that are spanned by the
            construct's data. If unset, and the *set_axes* parameter
            is True, then an attempt will be made to assign existing
            domain axis constructs to the data.
    
            The contents of the *axes* parameter is mapped to domain
            axis contructs by translating each element into a domain
            axis construct key via the `domain_axis` method.
    
            *Parameter example:*
              ``axes='domainaxis1'``
            
            *Parameter example:*
              ``axes='X'``
            
            *Parameter example:*
              ``axes=['latitude']``
            
            *Parameter example:*
              ``axes=['X', 'longitude']``
            
            *Parameter example:*
              ``axes=[1, 0]``
    
        set_axes: `bool`, optional
            If `False` then do not set the domain axes constructs that
            are spanned by the data, even if the *axes* parameter has
            been set. By default the axes are set either according to
            the *axes* parameter, or an attempt will be made to assign
            existing domain axis constructs to the data.
    
        copy: `bool`, optional
            If `True` then set a copy of the construct. By default the
            construct is not copied.
            
    :Returns:
    
        `str`
            The construct identifier for the construct.
        
    **Examples:**
    
    >>> key = f.set_construct(c)
    >>> key = f.set_construct(c, copy=False)
    >>> key = f.set_construct(c, axes='domainaxis2')
    >>> key = f.set_construct(c, key='cellmeasure0')

        '''
        construct_type = construct.construct_type
        
        if not set_axes:
            axes = None

        if construct_type in ('dimension_coordinate',
                              'auxiliary_coordinate',
                              'cell_measure'):
            if construct.isscalar:
                # Turn a scalar object into 1-d
                if copy:                    
                    construct = construct.insert_dimension(0)
                    copy = False
                else:
                    construct.insert_dimension(0, inplace=True)
            #-- End: if
            
            if set_axes:
                axes = self._set_construct_parse_axes(construct, axes,
                                                      allow_scalar=False)

        elif construct_type in ('domain_ancillary',
                                'field_ancillary'):
            if set_axes:
                axes = self._set_construct_parse_axes(construct, axes,
                                                      allow_scalar=True)
        #--- End: if

        if construct_type == 'dimension_coordinate':
            for dim, dim_axes in self.constructs.filter_by_type(construct_type).data_axes().items():
                if dim == key:
                    continue
                
                if dim_axes == tuple(axes):
                    self.del_construct(dim, default=None)
        #--- End: if
            
        out = super().set_construct(construct, key=key, axes=axes, copy=copy)
    
        if construct_type == 'dimension_coordinate':
            self._conform_coordinate_references(out) #, coordinate=True)
            self.autocyclic()
            self._conform_cell_methods()
            
        elif construct_type == 'auxiliary_coordinate':
            self._conform_coordinate_references(out) #, coordinate=True)
            self._conform_cell_methods()

        elif construct_type == 'cell_method':
            self._conform_cell_methods()

        elif construct_type == 'coordinate_reference':
            for ckey in self.coordinates:
                self._conform_coordinate_references(ckey) #, coordinate=True)
        #--- End: if

        # Return the construct key
        return out


    def get_data_axes(self, identity=None, default=ValueError()):
        '''Return the keys of the domain axis constructs spanned by the data
    of a metadata construct.
    
    .. versionadded:: 3.0.0
    
    .. seealso:: `del_data_axes`, `has_data_axes`, `set_data_axes`
    
    :Parameters:
    
        identity: optional
           Select the construct for which to return the domain axis
           constructs spanned by its data. By default the field
           construct is selected. May be:
    
              * The identity or key of a metadata construct.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``,
            ``'ncvar%lat'``, etc.); or a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', 'T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
            
        default: optional
            Return the value of the *default* parameter if the data
            axes have not been set. If set to an `Exception` instance
            then it will be raised instead.
    
    :Returns:
    
        `tuple` 
            The keys of the domain axis constructs spanned by the data.
    
    **Examples:**
    
    >>> f.set_data_axes(['domainaxis0', 'domainaxis1'])
    >>> f.get_data_axes()
    ('domainaxis0', 'domainaxis1')
    >>> f.del_data_axes()
    ('domainaxis0', 'domainaxis1')
    >>> print(f.del_dataxes(None))
    None
    >>> print(f.get_data_axes(default=None))
    None
    
    TODO more examples with key=

        '''
        if identity is None:
            return super().get_data_axes(default=default)
        
        key = self.construct_key(identity, default=None)
        if key is None:
            return self.construct_key(identity, default=default)

        return super().get_data_axes(key=key, default=default)


    def period(self, axis, **kwargs):
        '''Return the period of an axis.

    Note that a non-cyclic axis may have a defined period.
    
    .. versionadded:: 1.0
    
    .. seealso:: `axis`, `cyclic`, `iscyclic`,
                 `cf.DimensionCoordinate.period`
    
    :Parameters:
    
        axis:
            The cyclic axis, defined by that which would be selected
            by passing the given axis description to a call of the
            field's `domain_axis` method. For example, for a value of
            ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.
    
        axes: deprecated at version 3.0.0
            Use the *axis* parameter instead.

        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Data` or `None`
            The period of the cyclic axis's dimension coordinates, or
            `None` no period has been set.
    
    **Examples:**
    
    >>> f.cyclic()
    {}
    >>> print(f.period('X'))
    None
    >>> f.dimension_coordinate('X').Units
    <CF Units: degrees_east>
    >>> f.cyclic('X', period=360)
    {}
    >>> print(f.period('X'))
    <CF Data(): 360.0 'degrees_east'>
    >>> f.cyclic('X', False)
    {'dim3'}
    >>> print(f.period('X'))
    <CF Data(): 360.0 'degrees_east'>
    >>> f.dimension_coordinate('X').period(None)
    <CF Data(): 360.0 'degrees_east'>
    >>> print(f.period('X'))
    None

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'period', kwargs) # pragma: no cover
            
        axis = self.domain_axis(axis, key=True, default=ValueError(
                "Can't identify axis from: {!r}".format(axis)))

        dim = self.dimension_coordinates.filter_by_axis('and', axis).value(None)
        if dim is None:
            return
            
        return dim.period()       


    def replace_construct(self, identity, construct, copy=True):
        '''Replace a metadata construct.
                          

    Replacement assigns the same construct key and, if applicable, the
    domain axes of the original construct to the new, replacing
    construct.

    .. versionadded:: 3.0.0
    
    .. seealso:: `set_construct`
    
    :Parameters:
    
        identity:
            Select the metadata construct to be replaced by one of:
    
              * The identity or key of a metadata construct.
    
              * The identity or key of a domain axis construct that is
                spanned by a metadata construct's data.
    
            A construct identity is specified by a string
            (e.g. ``'latitude'``, ``'long_name=time'``, ``'ncvar%lat'``,
            etc.); a `Query` object (e.g. ``cf.eq('longitude')``); or
            a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            A construct has a number of identities, and is selected if
            any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            six identities:
    
               >>> x.identities()
               ['time', 'long_name=Time', 'foo=bar', 'standard_name=time', 'ncvar%t', T']
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'dimensioncoordinate2'`` and
            ``'key%dimensioncoordinate2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='Y'``
    
            *Parameter example:*
              ``identity='latitude'``
    
            *Parameter example:*
              ``identity='long_name=Latitude'``
    
            *Parameter example:*
              ``identity='dimensioncoordinate1'``
    
            *Parameter example:*
              ``identity='domainaxis2'``
    
            *Parameter example:*
              ``identity='ncdim%y'``
  
        construct:
           The new construct to replace that selected by the
           *identity* parameter.

        copy: `bool`, optional
            If `True` then set a copy of the new construct. By default
            the construct is not copied.
    
    :Returns:
    
            The construct that was replaced.
    
    **Examples:**
    
    >>> f.replace_construct('X', new_X_construct)

        '''
        key = self.construct(identity, key=True, default=ValueError('TODO a'))
        c = self.constructs[key]

        set_axes = True
        
        if not isinstance(construct, c.__class__):
            raise ValueError('TODO')

        axes = self.get_data_axes(key, None)
        if axes is not None:
            shape0 = getattr(c, 'shape', None)
            shape1 = getattr(construct, 'shape', None)
            if shape0 != shape1:
                raise ValueError('TODO')
        #--- End: if
        
        self.set_construct(construct, key=key, axes=axes, copy=copy)

        return c

    def roll(self, axis, shift, inplace=False, i=False, **kwargs):
        '''Roll the field along a cyclic axis.

    A unique axis is selected with the axes and kwargs parameters.
    
    .. versionadded:: 1.0
    
    .. seealso:: `anchor`, `axis`, `cyclic`, `iscyclic`, `period`
    
    :Parameters:
    
        axis: 
            The cyclic axis to be rolled, defined by that which would
            be selected by passing the given axis description to a
            call of the field's `domain_axis` method. For example, for
            a value of ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.

        shift: `int`
            The number of places by which the selected cyclic axis is
            to be rolled.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        kwargs: deprecated at version 3.0.0
    
    :Returns:
    
        `Field`
            The rolled field.
    
    **Examples:**
    
    Roll the data of the 'X' axis one elements to the right:

    >>> f.roll('X', 1)

    Roll the data of the 'X' axis three elements to the left:

    >>> f.roll('X', -3)

        '''          
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'roll', i=True) # pragma: no cover

        axis = self.domain_axis(axis, key=True,
                                default=ValueError(
                                    "Can't roll: Bad axis specification: {!r}".format(axis)))
            
        if inplace:
            f = self
        else:
            f = self.copy()
        
        if self.domain_axes[axis].get_size() <= 1:
            if inplace:
                f = None
            return f
        
        dim = self.dimension_coordinates.filter_by_axis('exact', axis).value(None)
        if dim is not None and dim.period() is None:
            raise ValueError(
                "Can't roll: {!r} axis has non-periodic dimension coordinates".format(
                    dim.identity()))

        try:
            iaxis = self.get_data_axes().index(axis)
        except ValueError:
            if inplace:
                f = None
            return f

        super(Field, f).roll(iaxis, shift, inplace=True)

        for key, construct in f.constructs.filter_by_data().items():
            axes = f.get_data_axes(key, default=())
            if axis in axes:
                construct.roll(axes.index(axis), shift, inplace=True)
        #--- End: for

        if inplace:
            f = None
        return f


    def where(self, condition, x=None, y=None, inplace=False,
              construct=None, i=False, _debug=False, item=None,
              **item_options):
        '''Assign to data elements depending on a condition.

    Data can be changed by assigning to elements that are selected by
    a condition based on the data values of the field construct or on
    its metadata constructs.
    
    Different values can be assigned to where the conditions are, and
    are not, met.
    
    **Missing data**
    
    Data array elements may be set to missing values by assigning them
    to the `cf.masked` constant, or by assignment missing data
    elements of array-valued *x* and *y* parameters.
    
    By default the data mask is "hard", meaning that masked values can
    not be changed by assigning them to another value. This behaviour
    may be changed by setting the `hardmask` attribute of the field
    construct to `False`, thereby making the data mask "soft" and
    allowing masked elements to be set to non-masked values.
    
    .. seealso:: `cf.masked`, `hardmask`, `indices`, `mask`,
                 `subspace`, `__setitem__`
    
    :Parameters:
    
        condition: 
            The condition which determines how to assign values to the
            data.
    
            In general it may be any scalar or array-like object (such
            as a `numpy`, `Data` or `Field` object) that is
            broadcastable to the shape of the data. Assignment from
            the *x* and *y* parameters will be done where elements of
            the condition evaluate to `True` and `False` respectively.
    
            *Parameter example:*
              ``f.where(f.data<0, x=-999)`` will set all data values
              that are less than zero to -999.
    
            *Parameter example:*
              ``f.where(True, x=-999)`` will set all data values to
              -999. This is equivalent to ``f[...] = -999``.
    
            *Parameter example:*
              ``f.where(False, y=-999)`` will set all data values to
              -999. This is equivalent to ``f[...] = -999``.
    
            *Parameter example:*
              If field construct ``f`` has shape ``(5, 3)`` then
              ``f.where([True, False, True], x=-999, y=cf.masked)``
              will set data values in columns 0 and 2 to -999, and
              data values in column 1 to missing data. This works
              because the condition has shape ``(3,)`` which
              broadcasts to the field's shape.
    
            If *condition* is a `Query` object then this implies a
            condition defined by applying the query to the field
            construct's data (or a metadata construct's data if the
            *construct* parameter is set).
    
            *Parameter example:*
              ``f.where(cf.lt(0), x=-999)`` will set all data values
              that are less than zero to -999. This is equivalent to
              ``f.where(f.data<0, x=-999)``.
            
            If *condition* is another field construct then it is first
            transformed so that it is broadcastable to the data being
            assigned to. This is done by using the metadata constructs
            of the two field constructs to create a mapping of
            physically identical dimensions between the fields, and
            then manipulating the dimensions of other field
            construct's data to ensure that they are broadcastable. If
            either of the field constructs does not have sufficient
            metadata to create such a mapping then an exception will
            be raised. In this case, any manipulation of the
            dimensions must be done manually, and the `Data` instance
            of *construct* (rather than the field construct itself)
            may be used for the condition.
    
            *Parameter example:*
              If field construct ``f`` has shape ``(5, 3)`` and ``g =
              f.transpose() < 0`` then ``f.where(g, x=-999)`` will set
              all data values that are less than zero to -999,
              provided there are sufficient metadata for the data
              dimensions to be mapped. However, ``f.where(g.data,
              x=-999)`` will always fail in this example, because the
              shape of the condition is ``(3, 5)``, which does not
              broadcast to the shape of the ``f``.
    
        x, y: *optional*
            Specify the assignment values. Where the condition
            evaluates to `True`, assign to the field's data from *x*,
            and where the condition evaluates to `False`, assign to
            the field's data from *y*. The *x* and *y* parameters are
            each one of:
    
            * `None`. The appropriate data elements array are
              unchanged. This the default.
    
            * Any scalar or array-like object (such as a `numpy`,
              `Data` or `Field` object) that is broadcastable to the
              shape of the data.
    
        ..
    
            *Parameter example:*
              ``f.where(condition)``, for any ``condition``, returns a
              field construct with identical data values.
    
            *Parameter example:* 
              ``f.where(cf.lt(0), x=-f.data, y=cf.masked)`` will
              change the sign of all negative data values, and set all
              other data values to missing data.
    
            If *x* or *y* is another field construct then it is first
            transformed so that its data is broadcastable to the data
            being assigned to. This is done by using the metadata
            constructs of the two field constructs to create a mapping
            of physically identical dimensions between the fields, and
            then manipulating the dimensions of other field
            construct's data to ensure that they are broadcastable. If
            either of the field constructs does not have sufficient
            metadata to create such a mapping then an exception will
            be raised. In this case, any manipulation of the
            dimensions must be done manually, and the `Data` instance
            of *x* or *y* (rather than the field construct itself) may
            be used for the condition.
    
            *Parameter example:*
              If field construct ``f`` has shape ``(5, 3)`` and ``g =
              f.transpose() * 10`` then ``f.where(cf.lt(0), x=g)``
              will set all data values that are less than zero to the
              equivalent elements of field construct ``g``, provided
              there are sufficient metadata for the data dimensions to
              be mapped. However, ``f.where(cf.lt(0), x=g.data)`` will
              always fail in this example, because the shape of the
              condition is ``(3, 5)``, which does not broadcast to the
              shape of the ``f``.
    
        construct: `str`, optional
            Define the condition by applying the *construct* parameter
            to the given metadata construct's data, rather then the
            data of the field construct. Must be
    
            * The identity or key of a metadata coordinate construct
              that has data.
    
        ..
    
            The *construct* parameter selects the metadata construct
            that is returned by this call of the field's `construct`
            method: ``f.construct(construct)``. See
            `cf.Field.construct` for details.
    
            *Parameter example:*
              ``f.where(cf.wi(-30, 30), x=cf.masked,
              construct='latitude')`` will set all data values within
              30 degrees of the equator to missing data.
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
        item: deprecated at version 3.0.0
            Use the *constuct* parameter instead.
    
        item_options: deprecated at version 3.0.0
    
    :Returns:
    
        `Field` or `None`
            A new field construct with an updated data array, or
            `None` if the operation was in-place.
    
    **Examples:**
    
    Set data array values to 15 everywhere:
    
    >>> f.where(True, 15)
    
    This example could also be done with subspace assignment:
    
    >>> f[...] = 15
    
    Set all negative data array values to zero and leave all other
    elements unchanged:
    
    >>> g = f.where(f<0, 0)
    
    Multiply all positive data array elements by -1 and set other data
    array elements to 3.14:
    
    >>> g = f.where(f>0, -f, 3.14)
    
    Set all values less than 280 and greater than 290 to missing data:
    
    >>> g = f.where((f < 280) | (f > 290), cf.masked)
    
    This example could also be done with a `Query` object:
    
    >>> g = f.where(cf.wo(280, 290), cf.masked)
    
    or equivalently:
    
    >>> g = f.where(f==cf.wo(280, 290), cf.masked)
    
    Set data array elements in the northern hemisphere to missing data
    in-place:
    
    >>> condition = f.domain_mask(latitude=cf.ge(0))
    >>> f.where(condition, cf.masked, inplace=True)
    
    Missing data can only be changed if the mask is "soft":
    
    >>> f[0] = cf.masked
    >>> g = f.where(True, 99)
    >>> print(g[0],array)
    [--]
    >>> f.hardmask = False
    >>> g = f.where(True, 99)
    >>> print(g[0],array)
    [99]
    
    This in-place example could also be done with subspace assignment
    by indices:
    
    >>> northern_hemisphere = f.indices(latitude=cf.ge(0))
    >>> f.subspace[northern_hemisphere] = cf.masked
    
    Set a polar rows to their zonal-mean values:
    
    >>> condition = f.domain_mask(latitude=cf.set([-90, 90]))
    >>> g = f.where(condition, f.collapse('longitude: mean'))

        '''
        if i:            
            _DEPRECATION_ERROR_KWARGS(self, 'where', i=True) # pragma: no cover

        if item is not None:
            _DEPRECATION_ERROR_KWARGS(self, 'where', {'item': item},
                                      "Use keyword 'construct' instead.") # pragma: no cover

        if item_options:
            _DEPRECATION_ERROR_KWARGS(self, 'where', {'item_options': item_options}) # pragma: no cover

        if x is None and y is None:
            if inplace:
                return
            return self.copy()

        self_class = self.__class__

        if isinstance(condition, self_class):
            # --------------------------------------------------------
            # Condition is another field construct
            # --------------------------------------------------------
            condition = self._conform_for_assignment(condition)

        elif construct is not None:
            if not isinstance(condition, Query):
                raise ValueError(
                    "A condition on a metadata construct must be a Query object")
            
            # Apply the Query to a metadata construct of the field,
            # making sure that the construct's data is broadcastable
            # to the field's data.
            g = self.transpose(self.get_data_axes(), constructs=True)

            key = g.construct_key(construct,
                                  default=ValueError("Can't identify unique {!r} construct".format(
                                      construct)))
            construct = g.constructs[key]

            construct_data_axes = g.get_data_axes(key, default=None)
            if construct_data_axes is None:
                raise ValueError("TODO")
            
            data_axes = g.get_data_axes()
            
            if construct_data_axes != data_axes:
                s = [i for i, axis in enumerate(construct_data_axes)
                     if axis not in data_axes]
                if s:
                    construct.squeeze(s, inplace=True)
                    construct_data_axes = [axis for axis in construct_data_axes
                                           if axis not in data_axes]

                for i, axis in enumerate(data_axes):
                    if axis not in construct_data_axes:
                        construct.insert_dimension(i, inplace=True)
            #--- End: if
#TODO some error checking, here

            condition = condition.evaluate(construct).get_data()
        #--- End: if

        if x is not None and isinstance(x, self_class):
            x = self._conform_for_assignment(x)
               
        if y is not None and isinstance(y, self_class):
            y = self._conform_for_assignment(y)

        return super().where(condition, x, y, inplace=inplace, _debug=_debug)  


    @property
    def subspace(self):
        '''Create a subspace of the field.

    The subspace retains all of the metadata of the original field, with
    those metadata items that contain data arrays also subspaced.
    
    A subspace may be defined in "metadata-space" via conditionss on the
    data array values of its domain items: dimension coordinate, auxiliary
    coordinate, cell measure, domain ancillary and field ancillary
    objects.
    
    Alternatively, a subspace may be defined be in "index-space" via
    explicit indices for the data array using an extended Python slicing
    syntax.
    
    .. seealso:: `indices`, `where`, `__getitem__`
    
    **Size one axes**
    
      Size one axes in the data array of the subspaced field are always
      retained, but may be subsequently removed with the field's
      `~cf.Field.squeeze` method:
    
    
    **Defining a subspace in metadata-space**
    
      Defining a subspace in metadata-space has the following features
      
      * Axes to be subspaced may identified by metadata, rather than their
        position in the data array.
      
      * The position in the data array of each axis need not be known and
        the axes to be subspaced may be given in any order.
      
      * Axes for which no subspacing is required need not be specified.
      
      * Size one axes of the domain which are not spanned by the data
        array may be specified.
      
      * The field may be subspaced according to conditions on
        multidimensional items.
      
      Subspacing in metadata-space is configured with the following
      parameters:
    
      :Parameters:
        
          positional arguments: *optional*
              Configure the type of subspace that is created. Zero or one
              of:
        
                ==============  ==========================================
                *argument*      Description
                ==============  ==========================================
                ``'compress'``  The default. Create the smallest possible
                                subspace that contains the selected
                                elements. As many non-selected elements
                                are discarded as possible, meaning that
                                the subspace may not form a contiguous
                                block of the original field. The subspace
                                may still contain non-selected elements, 
                                which are set to missing data.
                
                ``'envelope'``  Create the smallest subspace that
                                contains the selected elements and forms a
                                contiguous block of the original
                                field. Interior, non-selected elements are
                                set to missing data.
                
                ``'full'``      Create a subspace that is the same size as
                                the original field, but with all
                                non-selected elements set to missing data.
                ==============  ==========================================
    
              In addition the following optional argument specifies how to
              interpret the keyword parameter names:
    
                ==============  ==========================================
                *argument*      Description
                ==============  ==========================================
                ``'exact'``     Keyword parameters names are not treated
                                as abbreviations of item identities. By
                                default, keyword parameters names are
                                allowed to be abbreviations of item
                                identities.
                ==============  ==========================================
    
                *Parameter example:*
                  To create a subspace that is the same size as the
                  original field, but with missing data at non-selected
                  elements: ``f.subspace('full', **kwargs)``, where
                  ``**kwargs`` are the positional parameters that define
                  the selected elements.
        
          keyword parameters: *optional*
              Keyword parameter names identify items of the domain (such
              as a particular coordinate type) and their values set
              conditions on their data arrays (e.g. the actual coordinate
              values). These conditions define the subspace that is
              created.
    
          ..
      
              **Keyword names**
    
              A keyword name selects a unique item of the field. The name
              may be any value allowed by the *description* parameter of
              the field's `item` method, which is used to select a unique
              domain item. See `cf.Field.item` for details.
              
                *Parameter example:*           
                  The keyword ``lat`` will select the item returned by
                  ``f.item(description='lat')``. See the *exact*
                  positional argument.
      
                *Parameter example:*           
                  The keyword ``'T'`` will select the item returned by
                  ``f.item(description='T')``.
      
      
                *Parameter example:*           
                  The keyword ``'dim2'`` will select the item that has
                  this internal identifier
                  ``f.item(description='dim2')``. This can be useful in
                  the absence of any more meaningful metadata. A full list
                  of internal identifiers may be found with the field's
                  `items` method.
      
              **Keyword values**
    
              A keyword value specifies a selection on the selected item's
              data array which identifies the axis elements to be be
              included in the subspace.
    
          ..
      
              If the value is a `Query` object then then the query is
              applied to the item's data array to create the subspace.
    
                *Parameter example:*
                  To create a subspace for the northern hemisphere,
                  assuming that there is a coordinate with identity
                  "latitude": ``f.subspace(latitude=cf.ge(0))``
      
                *Parameter example:*
                  To create a subspace for the time 2018-08-27:
                  ``f.subspace(T=cf.dteq('2018-08-27'))``
      
                *Parameter example:*
                  To create a subspace for the northern hemisphere,
                  identifying the latitude coordinate by its long name:
                  ``f.subspace(**{'long_name:latitude': cf.ge(0)})``. In
                  this case it is necessary to use the ``**`` syntax
                  because the ``:`` character is not allowed in keyword
                  parameter names.
      
              If the value is a `list` of integers then these are used as
              the axis indices, without testing the item's data array.
      
                *Parameter example:*
                  To create a subspace using the first, third, fourth and
                  last indices of the "X" axis: ``f.subspace(X=[0, 2, 3,
                  -1])``.
      
              If the value is a `slice` object then it is used as the axis
              indices, without testing the item's data array.
      
                *Parameter example:*
                  To create a subspace from every even numbered index
                  along the "Z" axis: ``f.subspace(Z=slice(0, None, 2))``.
      
              If the value is anything other thaqn a `Query`, `list` or
              `slice` object then, the subspace is defined by where the
              data array equals that value. I.e. ``f.subspace(name=x)`` is
              equivalent to ``f.subspace(name=cf.eq(x))``.
    
                *Parameter example:*
                  To create a subspace where latitude is 52 degrees north:
                  ``f.subspace(latitude=52)``. Note that this assumes that
                  the latitude coordinate are in units of degrees
                  north. If this were not known, either of
                  ``f.subspace(latitude=cf.Data(52, 'degrees_north'))``
                  and ``f.subspace(latitude=cf.eq(52, 'degrees_north'))``
                  would guarantee the correct result.
      
      :Returns:
    
          `Field`
              An independent field containing the subspace of the original
              field.
          
      **Multidimensional items**
    
      Subspaces defined by items which span two or more axes are
      allowed.
    
          *Parameter example:* 
            The subspace for the Nino Region 3 created by
            ``f.subspace(latitude=cf.wi(-5, 5), longitude=cf.wi(90,
            150))`` will work equally well if the latitude and longitude
            coordinates are stored in 1-d or 2-d arrays. In the latter
            case it is possble that the coordinates are curvilinear or
            unstructured, in which case the subspace may contain missing
            data for the non-selected elements.
    
      **Subspacing multiple axes simultaneously**
    
      To subspace multiple axes simultaneously, simply provide multiple
      keyword arguments.
    
        *Parameter example:*
          To create an eastern hemisphere tropical subspace:
          ``f.subspace(X=cf.wi(0, 180), latitude=cf.wi(-30, 30))``.
    
    
    **Defining a subspace in index-space**
    
      Subspacing in index-space uses an extended Python slicing syntax,
      which is similar to :ref:`numpy array indexing
      <numpy:arrays.indexing>`. Extensions to the numpy indexing
      functionality are:
    
      * When more than one axis's slice is a 1-d boolean sequence or 1-d
        sequence of integers, then these indices work independently along
        each axis (similar to the way vector subscripts work in Fortran),
        rather than by their elements.
      
      * Boolean indices may be any object which exposes the numpy array
        interface, such as the field's coordinate objects.
    
      :Returns:
    
          `Field`
              An independent field containing the subspace of the original
              field.
          
      **Examples:**
    
      >>> f
      <CF Field: air_temperature(time(12), latitude(73), longitude(96)) K>
      >>> f.subspace[:, [0, 72], [5, 4, 3]]
      <CF Field: air_temperature(time(12), latitude(2), longitude(3)) K>
      >>> f.subspace[:, f.coord('latitude')<0]
      <CF Field: air_temperature(time(12), latitude(36), longitude(96)) K>
    
    
    **Assignment to the data array**
    
      A subspace defined in index-space may have its data array values
      changed by assignment:
      
      >>> f
      <CF Field: air_temperature(time(12), latitude(73), longitude(96)) K>
      >>> f.subspace[0:6] = f.subspace[6:12]
      >>> f.subspace[..., 0:48] = -99
      
      To assign to a subspace defined in metadata-space, the equivalent
      index-space indices must first be found with the field's `indices`
      method, and then the assignment may be applied in index-space:
      
      >>> index = f.indices(longitude=cf.lt(180))
      >>> f.subspace[index] = cf.masked
      
      Note that the `indices` method accepts the same positional and
      keyword arguments as `subspace`.

        '''
        return SubspaceField(self)


    def coordinate_reference_domain_axes(self, identity):
        '''Return the domain axes that apply to a coordinate reference
    construct.

    :Parameters:

        identity:
            Select the coordinate reference construct by one of:
    
              * The identity or key of a coordinate reference construct.
    
            A construct identity is specified by a string
            (e.g. ``'grid_mapping_name:latitude_longitude'``,
            ``'latitude_longitude'``, ``'ncvar%lat_lon'``, etc.); a
            `Query` object (e.g. ``cf.eq('latitude_longitude')``); or
            a compiled regular expression
            (e.g. ``re.compile('^atmosphere')``) that selects the
            relevant constructs whose identities match via
            `re.search`.
    
            Each construct has a number of identities, and is selected
            if any of them match any of those provided. A construct's
            identities are those returned by its `!identities`
            method. In the following example, the construct ``x`` has
            two identites:
    
               >>> x.identities()
               ['grid_mapping_name:latitude_longitude', 'ncvar%lat_lon']
    
            A identity's prefix of ``'grid_mapping_name:'`` or
            ``'standard_name:'`` may be omitted
            (e.g. ``'standard_name:atmosphere_hybrid_height_coordinate'``
            and ``'atmosphere_hybrid_height_coordinate'`` are both
            acceptable identities).
    
            A construct key may optionally have the ``'key%'``
            prefix. For example ``'coordinatereference2'`` and
            ``'key%coordinatereference2'`` are both acceptable keys.
    
            Note that in the output of a `print` call or `!dump`
            method, a construct is always described by one of its
            identities, and so this description may always be used as
            an *identity* argument.
    
            *Parameter example:*
              ``identity='standard_name:atmosphere_hybrid_height_coordinate'``
    
            *Parameter example:*
              ``identity='grid_mapping_name:rotated_latitude_longitude'``
    
            *Parameter example:*
              ``identity='transverse_mercator'``
    
            *Parameter example:*
              ``identity='coordinatereference1'``
    
            *Parameter example:*
              ``identity='key%coordinatereference1'``
    
            *Parameter example:*
              ``identity='ncvar%lat_lon'``
    
    :Returns:
    
        `set`
            The identifiers of the domain axis constructs that san
            the data of all coordinate and domain ancillary constructs
            used by the selected coordinate reference construct.
    
    **Examples:**
    
    >>> f.coordinate_reference_domain_axes('coordinatereference0')
    {'domainaxis0', 'domainaxis1', 'domainaxis2'}

    >>> f.coordinate_reference_domain_axes('atmosphere_hybrid_height_coordinate')
    {'domainaxis0', 'domainaxis1', 'domainaxis2'}

        '''
        cr = self.coordinate_reference(identity)

        domain_axes = tuple(self.domain_axes)
        data_axes = self.constructs.data_axes()

        axes = []
        for i in cr.coordinates() | set(cr.coordinate_conversion.domain_ancillaries().values()):
            i = self.construct_key(i, None)
            axes.extend(data_axes.get(i, ()))
                                
        return set(axes)


    def section(self, axes=None, stop=None, **kwargs):
        '''Return a FieldList of m dimensional sections of a Field of n
    dimensions, where M <= N.
    
    :Parameters:
    
        axes: optional
            A query for the m axes that define the sections of the
            Field as accepted by the Field object's axes method. The
            keyword arguments are also passed to this method. See
            TODO cf.Field.axes for details. If an axis is returned that is
            not a data axis it is ignored, since it is assumed to be a
            dimension coordinate of size 1.
    
        stop: `int`, optional
            Stop after taking this number of sections and return. If
            *stop* is `None` all sections are taken.
    
    :Returns:
    
        `FieldList`
            The sections of the field construct.
    
    **Examples:**
    
    Section a field into 2D longitude/time slices, checking the units:
    
    >>> f.section({None: 'longitude', units: 'radians'},
    ...           {None: 'time', 'units': 'days since 2006-01-01 00:00:00'})
    
    Section a field into 2D longitude/latitude slices, requiring
    exact names:
    
    >>> f.section(['latitude', 'longitude'], exact=True)
    
    Section a field into 2D longitude/latitude slices, showing
    the results:
    
    >>> f
    <CF Field: eastward_wind(model_level_number(6), latitude(145), longitude(192)) m s-1>
    >>> f.section(('X', 'Y'))
    [<CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>,
     <CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>,
     <CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>,
     <CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>,
     <CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>,
     <CF Field: eastward_wind(model_level_number(1), latitude(145), longitude(192)) m s-1>]

        '''
        return FieldList(_section(self, axes, data=False, stop=stop, **kwargs))


    def regrids(self, dst, method, src_cyclic=None, dst_cyclic=None,
                use_src_mask=True, use_dst_mask=False,
                fracfield=False, src_axes=None, dst_axes=None,
                axis_order=None, ignore_degenerate=True,
                inplace=False, i=False, _compute_field_mass=None):
        '''Return the field regridded onto a new latitude-longitude grid.

    Regridding, also called remapping or interpolation, is the process
    of changing the grid underneath field data values while preserving
    the qualities of the original data.
    
    The regridding method must be specified. First-order conservative
    interpolation conserves the global area integral of the field, but
    may not give approximations to the values as good as bilinear
    interpolation. Bilinear interpolation is available. The latter
    method is particular useful for cases when the latitude and
    longitude coordinate cell boundaries are not known nor
    inferrable. Higher order patch recovery is available as an
    alternative to bilinear interpolation.  This typically results in
    better approximations to values and derivatives compared to the
    latter, but the weight matrix can be larger than the bilinear
    matrix, which can be an issue when regridding close to the memory
    limit on a machine. Nearest neighbour interpolation is also
    available. Nearest source to destination is particularly useful
    for regridding integer fields such as land use.
    

    **Metadata**
    
    The field's domain must have well defined X and Y axes with
    latitude and longitude coordinate values, which may be stored as
    dimension coordinate objects or two dimensional auxiliary
    coordinate objects. If the latitude and longitude coordinates are
    two dimensional then the X and Y axes must be defined by dimension
    coordinates if present or by the netCDF dimensions. In the latter
    case the X and Y axes must be specified using the *src_axes* or
    *dst_axes* keyword. The same is true for the destination grid, if
    it provided as part of another field.
    
    The cyclicity of the X axes of the source field and destination
    grid is taken into account. If an X axis is in fact cyclic but is
    not registered as such by its parent field (see
    `cf.Field.iscyclic`), then the cyclicity may be set with the
    *src_cyclic* or *dst_cyclic* parameters. In the case of two
    dimensional latitude and longitude dimension coordinates without
    bounds it will be necessary to specify *src_cyclic* or
    *dst_cyclic* manually if the field is global.
    
    The output field's coordinate objects which span the X and/or Y
    axes are replaced with those from the destination grid. Any fields
    contained in coordinate reference objects will also be regridded,
    if possible.
    

    **Mask**
    
    The data array mask of the field is automatically taken into
    account, such that the regridded data array will be masked in
    regions where the input data array is masked. By default the mask
    of the destination grid is not taken into account. If the
    destination field data has more than two dimensions then the mask,
    if used, is taken from the two dimensionsal section of the data
    where the indices of all axes other than X and Y are zero.
    

    **Implementation**
    
    The interpolation is carried by out using the `ESMF` package - a
    Python interface to the Earth System Modeling Framework (ESMF)
    regridding utility.
    

    **Logging**
    
    Whether ESMF logging is enabled or not is determined by
    `cf.REGRID_LOGGING`. If it is logging takes place after every
    call. By default logging is disabled.

    
    **Latitude-Longitude Grid**
    
    The canonical grid with independent latitude and longitude
    coordinates.
    

    **Curvilinear Grids**
    
    Grids in projection coordinate systems can be regridded as long as
    two dimensional latitude and longitude coordinates are present.

    
    **Rotated Pole Grids**
    
    Rotated pole grids can be regridded as long as two dimensional
    latitude and longitude coordinates are present. It may be
    necessary to explicitly identify the grid latitude and grid
    longitude coordinates as being the X and Y axes and specify the
    *src_cyclic* or *dst_cyclic* keywords.
    

    **Tripolar Grids**
    
    Tripolar grids are logically rectangular and so may be able to be
    regridded. If no dimension coordinates are present it will be
    necessary to specify which netCDF dimensions are the X and Y axes
    using the *src_axes* or *dst_axes* keywords. Connections across
    the bipole fold are not currently supported, but are not be
    necessary in some cases, for example if the points on either side
    are together without a gap. It will also be necessary to specify
    *src_cyclic* or *dst_cyclic* if the grid is global.
    
    .. versionadded:: 1.0.4
    
    .. sealso:: `regridc`

    :Parameters:
    
        dst: `Field` or `dict`
            The field containing the new grid. If dst is a field list
            the first field in the list is used. Alternatively a
            dictionary can be passed containing the keywords
            'longitude' and 'latitude' with either two 1D dimension
            coordinates or two 2D auxiliary coordinates. In the 2D
            case both coordinates must have their axes in the same
            order and this must be specified by the keyword 'axes' as
            either of the tuples ``('X', 'Y')`` or ``('Y', 'X')``.
    
        method: `str`
            Specify the regridding method. The *method* parameter must
            be one of:
    
              ======================  ====================================
              *method*                Description
              ======================  ====================================
              ``'bilinear'``          Bilinear interpolation.
    
              ``'patch'``             Higher order patch recovery.
    
              ``'conservative_1st'``  First-order conservative regridding
              or ``'conservative'``   will be used (requires both of the
                                      fields to have contiguous, non-
                                      overlapping bounds).
    
              ``'nearest_stod'``      Nearest neighbor interpolation is
                                      used where each destination point is
                                      mapped to the closest source point
    
              ``'nearest_dtos'``      Nearest neighbor interpolation is
                                      used where each source point is
                                      mapped to the closest destination
                                      point. A given destination point may
                                      receive input from multiple source
                                      points, but no source point will map
                                      to more than one destination point.
              ======================  ====================================
    
        src_cyclic: `bool`, optional
            Specifies whether the longitude for the source grid is
            periodic or not. If `None` then, if possible, this is
            determined automatically otherwise it defaults to False.
    
        dst_cyclic: `bool`, optional
            Specifies whether the longitude for the destination grid
            is periodic of not. If `None` then, if possible, this is
            determined automatically otherwise it defaults to False.
    
        use_src_mask: `bool`, optional
            For all methods other than 'nearest_stod', this must be
            True as it does not make sense to set it to False. For the
            'nearest_stod' method if it is True then points in the
            result that are nearest to a masked source point are
            masked. Otherwise, if it is False, then these points are
            interpolated to the nearest unmasked source points.
    
        use_dst_mask: `bool`, optional
            By default the mask of the data on the destination grid is
            not taken into account when performing regridding. If this
            option is set to true then it is. If the destination field
            has more than two dimensions then the first 2D slice in
            index space is used for the mask e.g. for an field varying
            with (X, Y, Z, T) the mask is taken from the slice (X, Y,
            0, 0).
    
        fracfield: `bool`, optional
            If the method of regridding is conservative the fraction
            of each destination grid cell involved in the regridding
            is returned instead of the regridded data if this is
            True. Otherwise this is ignored.
    
        src_axes: `dict`, optional
            A dictionary specifying the axes of the 2D latitude and
            longitude coordinates of the source field when no
            dimension coordinates are present. It must have keys 'X'
            and 'Y'.
    
            *Parameter example:*
              ``src_axes={'X': 'ncdim%x', 'Y': 'ncdim%y'}``
    
        dst_axes: `dict`, optional
            A dictionary specifying the axes of the 2D latitude and
            longitude coordinates of the destination field when no
            dimension coordinates are present. It must have keys 'X'
            and 'Y'.
    
            *Parameter example:*
              ``dst_axes={'X': 'ncdim%x', 'Y': 'ncdim%y'}``
    
        axis_order: sequence, optional
            A sequence of items specifying dimension coordinates as
            retrieved by the `dim` method. These determine the order
            in which to iterate over the other axes of the field when
            regridding X-Y slices. The slowest moving axis will be the
            first one specified. Currently the regridding weights are
            recalculated every time the mask of an X-Y slice changes
            with respect to the previous one, so this option allows
            the user to minimise how frequently the mask changes.
        
        ignore_degenerate: `bool`, optional
            True by default. Instructs ESMPy to ignore degenerate
            cells when checking the grids for errors. Regridding will
            proceed and degenerate cells will be skipped, not
            producing a result, when set to True. Otherwise an error
            will be produced if degenerate cells are found. This will
            be present in the ESMPy log files if `cf.REGRID_LOGGING`
            is set to True. As of ESMF 7.0.0 this only applies to
            conservative regridding.  Other methods always skip
            degenerate cells.
    
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
        
        _compute_field_mass: `dict`, optional
            If this is a dictionary then the field masses of the
            source and destination fields are computed and returned
            within the dictionary. The keys of the dictionary
            indicates the lat/long slice of the field and the
            corresponding value is a tuple containing the source
            field's mass and the destination field's mass. The
            calculation is only done if conservative regridding is
            being performed. This is for debugging purposes.
    
    :Returns:
    
        `Field`
            The regridded field.
    
    **Examples:**
    
    Regrid field ``f`` conservatively onto a grid contained in field
    ``g``:
    
    >>> h = f.regrids(g, 'conservative')
    
    Regrid f to the grid of g using bilinear regridding and forcing
    the source field f to be treated as cyclic.
    
    >>> h = f.regrids(g, src_cyclic=True, method='bilinear')
    
    Regrid f to the grid of g using the mask of g.
    
    >>> h = f.regrids(g, 'conservative_1st', use_dst_mask=True)
    
    Regrid f to 2D auxiliary coordinates lat and lon, which have their
    dimensions ordered 'Y' first then 'X'.
    
    >>> lat
    <CF AuxiliaryCoordinate: latitude(110, 106) degrees_north>
    >>> lon
    <CF AuxiliaryCoordinate: longitude(110, 106) degrees_east>
    >>> h = f.regrids({'longitude': lon, 'latitude': lat, 'axes': ('Y', 'X')}, 'conservative')
    
    Regrid field, f, on tripolar grid to latitude-longitude grid of
    field, g.
    
    >>> h = f.regrids(g, 'bilinear, src_axes={'X': 'ncdim%x', 'Y': 'ncdim%y'},
    ...               src_cyclic=True)
    
    Regrid f to the grid of g iterating over the 'Z' axis last and the
    'T' axis next to last to minimise the number of times the mask is
    changed.
    
    >>> h = f.regrids(g, 'nearest_dtos', axis_order='ZT')

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'regrids', i=True) # pragma: no cover

        # Initialise ESMPy for regridding if found
        manager = Regrid.initialize()

        if inplace:
            f = self
        else:
            f = self.copy()
            
        # If dst is a dictionary set flag
        dst_dict = not isinstance(dst, f.__class__)
#        if isinstance(dst, f.__class__):
#            dst_dict = False
#            # If dst is a field list use the first field
#            if isinstance(dst, FieldList):
#                dst = dst[0]
#        else:
#            dst_dict = True
        
        # Retrieve the source field's latitude and longitude coordinates
        src_axis_keys, src_axis_sizes, src_coord_keys, src_coords, \
            src_coords_2D = f._regrid_get_latlong('source', axes=src_axes)
        
        # Retrieve the destination field's latitude and longitude coordinates
        if dst_dict:
            # dst is a dictionary
            try:
                dst_coords = (dst['longitude'], dst['latitude'])
            except KeyError:
                raise ValueError("Keys 'longitude' and 'latitude' must be" +
                                 " specified for destination.")

            if dst_coords[0].ndim == 1:
                dst_coords_2D = False
                dst_axis_sizes = [coord.size for coord in dst_coords]
            elif dst_coords[0].ndim == 2:
                try:
                    dst_axes = dst['axes']
                except KeyError:
                    raise ValueError("Key 'axes' must be specified for 2D" +
                                     " latitude/longitude coordinates.")
                dst_coords_2D = True
                if dst_axes == ('X', 'Y'):
                    dst_axis_sizes = dst_coords[0].shape
                elif dst_axes == ('Y', 'X'):
                    dst_axis_sizes = dst_coords[0].shape[::-1]
                else:
                    raise ValueError("Keyword 'axes' must either be " +
                                     "('X', 'Y') or ('Y', 'X').")
                if dst_coords[0].shape != dst_coords[1].shape:
                    raise ValueError('Longitude and latitude coordinates for ' +
                                     'destination must have the same shape.')
            else:
                raise ValueError('Longitude and latitude coordinates for ' +
                                 'destination must have 1 or 2 dimensions.')

            dst_axis_keys = None
        else:
            # dst is a Field
            dst_axis_keys, dst_axis_sizes, dst_coord_keys, dst_coords, \
                dst_coords_2D = dst._regrid_get_latlong('destination',
                                                        axes=dst_axes)
        
        # Automatically detect the cyclicity of the source longitude if
        # src_cyclic is None
        if src_cyclic is None:
            src_cyclic = f.iscyclic(src_axis_keys[0])

        # Automatically detect the cyclicity of the destination longitude if
        # dst is not a dictionary and dst_cyclic is None
        if not dst_dict and dst_cyclic is None:
            dst_cyclic = dst.iscyclic(dst_axis_keys[0])
        elif dst_dict and dst_cyclic is None:            
            dst_cyclic = dst['longitude'].isperiodic

        # Get the axis indices and their order for the source field
        src_axis_indices, src_order = \
                            f._regrid_get_axis_indices(src_axis_keys)

        # Get the axis indices and their order for the destination field.
        if not dst_dict:
            dst = dst.copy()
            dst_axis_indices, dst_order = \
                            dst._regrid_get_axis_indices(dst_axis_keys)
        
        # Get the order of the X and Y axes for each 2D auxiliary coordinate.
        src_coord_order = None
        dst_coord_order = None
        if src_coords_2D:
            src_coord_order = self._regrid_get_coord_order(src_axis_keys,
                                                           src_coord_keys)

        if dst_coords_2D:
            if dst_dict:
                if dst_axes == ('X', 'Y'):
                    dst_coord_order = [[0, 1], [0, 1]]
                elif dst_axes == ('Y', 'X'):
                    dst_coord_order = [[1, 0], [1, 0]]
                else:
                    raise ValueError("Keyword 'axes' must either be " +
                                     "('X', 'Y') or ('Y', 'X').")
            else:
                dst_coord_order = dst._regrid_get_coord_order(dst_axis_keys,
                                                              dst_coord_keys)
        #--- End: if
        
        # Get the shape of each section after it has been regridded.
        shape = self._regrid_get_section_shape(dst_axis_sizes,
                                               src_axis_indices)

        # Check the method
        self._regrid_check_method(method)
        
        # Check that use_src_mask is True for all methods other than
        # nearest_stod
        self._regrid_check_use_src_mask(use_src_mask, method)

        # Check the bounds of the coordinates
        self._regrid_check_bounds(src_coords, dst_coords, method)
        
        # Slice the source data into 2D latitude/longitude sections,
        # also getting a list of dictionary keys in the order
        # requested. If axis_order has not been set, then the order is
        # random, and so in this case the order in which sections are
        # regridded is random.
        section_keys, sections = self._regrid_get_reordered_sections(axis_order,
                                     src_axis_keys, src_axis_indices)
        
        # Bounds must be used if the regridding method is conservative.
        use_bounds = self._regrid_use_bounds(method)
        
        # Retrieve the destination field's mask if appropriate
        dst_mask = None
        if not dst_dict and use_dst_mask and dst.data.ismasked:
            dst_mask = dst._regrid_get_destination_mask(dst_order)
        
        # Retrieve the destination ESMPy grid and fields
        dstgrid = Regrid.create_grid(dst_coords, use_bounds, mask=dst_mask,
                                     cyclic=dst_cyclic, coords_2D=dst_coords_2D,
                                     coord_order=dst_coord_order)
        # dstfield will be reused to receive the regridded source data
        # for each section, one after the other
        dstfield = Regrid.create_field(dstgrid, 'dstfield')
        dstfracfield = Regrid.create_field(dstgrid, 'dstfracfield')

        # Regrid each section
        old_mask = None
        unmasked_grid_created = False
        for k in section_keys:
            d = sections[k]  # d is a Data object
            # Retrieve the source field's grid, create the ESMPy grid and a
            # handle to regridding.dst_dict
            src_data = d.squeeze().transpose(src_order).array
            if (not (method == 'nearest_stod' and use_src_mask)
                and numpy_ma_is_masked(src_data)):
                mask = src_data.mask
                if not numpy_array_equal(mask, old_mask):
                    # Release old memory
                    if old_mask is not None:
                        regridSrc2Dst.destroy()
                        srcfracfield.destroy()
                        srcfield.destroy()
                        srcgrid.destroy()

                    # (Re)create the source ESMPy grid and fields
                    srcgrid = Regrid.create_grid(src_coords, use_bounds,
                                                 mask=mask, cyclic=src_cyclic,
                                                 coords_2D=src_coords_2D,
                                                 coord_order=src_coord_order)
                    srcfield = Regrid.create_field(srcgrid, 'srcfield')
                    srcfracfield = Regrid.create_field(srcgrid, 'srcfracfield')
                    # (Re)initialise the regridder
                    regridSrc2Dst = Regrid(srcfield, dstfield, srcfracfield,
                                           dstfracfield, method=method,
                                           ignore_degenerate=ignore_degenerate)
                    old_mask = mask
            else:
                # The source data for this section is either a) not
                # masked or b) has the same mask as the previous
                # section.
                if not unmasked_grid_created or old_mask is not None:
                    # Create the source ESMPy grid and fields
                    srcgrid = Regrid.create_grid(src_coords, use_bounds,
                                                 cyclic=src_cyclic,
                                                 coords_2D=src_coords_2D,
                                                 coord_order=src_coord_order)
                    srcfield = Regrid.create_field(srcgrid, 'srcfield')
                    srcfracfield = Regrid.create_field(srcgrid, 'srcfracfield')
                    # Initialise the regridder. This also creates the
                    # weights needed for the regridding.
                    regridSrc2Dst = Regrid(srcfield, dstfield, srcfracfield,
                                           dstfracfield, method=method,
                                           ignore_degenerate=ignore_degenerate)
                    unmasked_grid_created = True
                    old_mask = None
            #--- End: if
            
            # Fill the source and destination fields (the destination
            # field gets filled with a fill value, the source field
            # with the section's data)
            self._regrid_fill_fields(src_data, srcfield, dstfield)
            
            # Run regridding (dstfield is an ESMF field)
            dstfield = regridSrc2Dst.run_regridding(srcfield, dstfield)

            # Compute field mass if requested for conservative regridding
            if (_compute_field_mass is not None and method in
                ('conservative', 'conservative_1st', 'conservative_2nd')):
                # Update the _compute_field_mass dictionary in-place,
                # thereby making the field mass available after
                # returning
                self._regrid_compute_field_mass(_compute_field_mass,
                                                k, srcgrid, srcfield,
                                                srcfracfield, dstgrid,
                                                dstfield)
            
            # Get the regridded data or frac field as a numpy array
            # (regridded_data is a numpy array)
            regridded_data = self._regrid_get_regridded_data(method,
                                                             fracfield,
                                                             dstfield,
                                                             dstfracfield)
            
            # Insert regridded data, with axes in order of the
            # original section. This puts the regridded data back into
            # the sections dictionary, with the same key, as a new
            # Data object. Note that the reshape is necessary to
            # replace any size 1 dimensions that we squeezed out
            # earlier.
            sections[k] = \
                Data(regridded_data.transpose(src_order).reshape(shape),
                     units=self.Units)
        #--- End: for
        
        # Construct new data from regridded sdst_dictections
        new_data = Data.reconstruct_sectioned_data(sections)
        
        # Construct new field
        if inplace:
            f = self
        else:
            f = self.copy()
        
        # Update ancillary variables of new field
        #f._conform_ancillary_variables(src_axis_keys, keep_size_1=False)

        # Update coordinate references of new field
        f._regrid_update_coordinate_references(dst, src_axis_keys,
                                               method, use_dst_mask,
                                               src_cyclic=False,
                                               dst_cyclic=False)
        
        # Update coordinates of new field
        f._regrid_update_coordinates(dst, dst_dict, dst_coords,
                                     src_axis_keys, dst_axis_keys,
                                     dst_axis_sizes=dst_axis_sizes,
                                     dst_coords_2D=dst_coords_2D,
                                     dst_coord_order=dst_coord_order)

        # Copy across the destination fields coordinate references if necessary
        if not dst_dict:
            f._regrid_copy_coordinate_references(dst, dst_axis_keys)

        # Insert regridded data into new field
        f.set_data(new_data, axes=self.get_data_axes(), copy=False)
        
        # Set the cyclicity of the destination longitude
        x = f.dimension_coordinate('X')
        if x is not None and x.Units.equivalent(Units('degrees')):
            f.cyclic('X', iscyclic=dst_cyclic, period=Data(360, 'degrees'))
        
        # Release old memory from ESMF (this ought to happen garbage
        # collection, but it doesn't seem to work there!)
        regridSrc2Dst.destroy()
        dstfracfield.destroy()
        srcfracfield.destroy()
        dstfield.destroy()
        srcfield.destroy()
        dstgrid.destroy()
        srcgrid.destroy()
        
#        if f.data.fits_in_one_chunk_in_memory(f.data.dtype.itemsize):
#            f.varray

        return f


    def regridc(self, dst, axes, method, use_src_mask=True,
                use_dst_mask=False, fracfield=False, axis_order=None,
                ignore_degenerate=True, inplace=False, i=False,
                _compute_field_mass=None):
        '''Return the field with the specified Cartesian axes regridded onto a
    new grid.
    
    Between 1 and 3 dimensions may be regridded.
    
    Regridding, also called remapping or interpolation, is the process
    of changing the grid underneath field data values while preserving
    the qualities of the original data.
    
    The regridding method must be specified. First-order conservative
    interpolation conserves the global spatial integral of the field,
    but may not give approximations to the values as good as
    (multi)linear interpolation. (Multi)linear interpolation is
    available. The latter method is particular useful for cases when
    the latitude and longitude coordinate cell boundaries are not
    known nor inferrable. Higher order patch recovery is available as
    an alternative to (multi)linear interpolation.  This typically
    results in better approximations to values and derivatives
    compared to the latter, but the weight matrix can be larger than
    the bilinear matrix, which can be an issue when regridding close
    to the memory limit on a machine. It is only available in
    2D. Nearest neighbour interpolation is also available. Nearest
    source to destination is particularly useful for regridding
    integer fields such as land use.
    

    **Metadata**
    
    The field's domain must have axes matching those specified in
    *src_axes*. The same is true for the destination grid, if it
    provided as part of another field. Optionally the axes to use from
    the destination grid may be specified separately in *dst_axes*.
    
    The output field's coordinate objects which span the specified
    axes are replaced with those from the destination grid. Any fields
    contained in coordinate reference objects will also be regridded,
    if possible.

    
    **Mask**
    
    The data array mask of the field is automatically taken into
    account, such that the regridded data array will be masked in
    regions where the input data array is masked. By default the mask
    of the destination grid is not taken into account. If the
    destination field data has more dimensions than the number of axes
    specified then, if used, its mask is taken from the 1-3
    dimensional section of the data where the indices of all axes
    other than X and Y are zero.
    

    **Implementation**
    
    The interpolation is carried by out using the `ESMF` package - a
    Python interface to the Earth System Modeling Framework (ESMF)
    regridding utility.
    

    **Logging**
    
    Whether ESMF logging is enabled or not is determined by
    `cf.REGRID_LOGGING`. If it is logging takes place after every
    call. By default logging is disabled.
    
    .. sealso:: `regrids`

    :Parameters:
    
        dst: `Field` or `dict`
            The field containing the new grid or a dictionary with the
            axes specifiers as keys referencing dimension coordinates.
            If dst is a field list the first field in the list is
            used.
    
        axes:
            Select dimension coordinates from the source and
            destination fields for regridding. See `cf.Field.axes` TODO for
            options for selecting specific axes. However, the number
            of axes returned by `cf.Field.axes` TODO must be the same as
            the number of specifiers passed in.
    
        method: `str`
            Specify the regridding method. The *method* parameter must be
            one of:
    
              ======================  ====================================
              *method*                Description
              ======================  ====================================
              ``'bilinear'``          (Multi)linear interpolation.
    
              ``'patch'``             Higher order patch recovery.
    
              ``'conservative_1st'``  First-order conservative regridding
              or ``'conservative'``   will be used (requires both of the
                                      fields to have contiguous, non-
                                      overlapping bounds).
    
              ``'nearest_stod'``      Nearest neighbor interpolation is
                                      used where each destination point is
                                      mapped to the closest source point
    
              ``'nearest_dtos'``      Nearest neighbor interpolation is
                                      used where each source point is
                                      mapped to the closest destination
                                      point. A given destination point may
                                      receive input from multiple source
                                      points, but no source point will map
                                      to more than one destination point.
              ======================  ====================================
    
        use_src_mask: `bool`, optional
            For all methods other than 'nearest_stod', this must be
            True as it does not make sense to set it to False. For the
    
            'nearest_stod' method if it is True then points in the
            result that are nearest to a masked source point are
            masked. Otherwise, if it is False, then these points are
            interpolated to the nearest unmasked source points.
    
        use_dst_mask: `bool`, optional
            By default the mask of the data on the destination grid is
            not taken into account when performing regridding. If this
            option is set to True then it is.
    
        fracfield: `bool`, optional
            If the method of regridding is conservative the fraction
            of each destination grid cell involved in the regridding
            is returned instead of the regridded data if this is
            True. Otherwise this is ignored.
    
        axis_order: sequence, optional
            A sequence of items specifying dimension coordinates as
            retrieved by the `dim` method. These determine the order
            in which to iterate over the other axes of the field when
            regridding slices. The slowest moving axis will be the
            first one specified. Currently the regridding weights are
            recalculated every time the mask of a slice changes with
            respect to the previous one, so this option allows the
            user to minimise how frequently the mask changes.
        
        ignore_degenerate: `bool`, optional
            True by default. Instructs ESMPy to ignore degenerate
            cells when checking the grids for errors. Regridding will
            proceed and degenerate cells will be skipped, not
            producing a result, when set to True. Otherwise an error
            will be produced if degenerate cells are found. This will
            be present in the ESMPy log files if cf.REGRID_LOGGING is
            set to True. As of ESMF 7.0.0 this only applies to
            conservative regridding.  Other methods always skip
            degenerate cells.
    
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
        
        _compute_field_mass: `dict`, optional
            If this is a dictionary then the field masses of the
            source and destination fields are computed and returned
            within the dictionary. The keys of the dictionary
            indicates the lat/long slice of the field and the
            corresponding value is a tuple containing the source
            field's mass and the destination field's mass. The
            calculation is only done if conservative regridding is
            being performed. This is for debugging purposes.
    
    :Returns:
    
        `Field` or `None
            The regridded field construct, or `None` if the operation
            was in-place.
    
    **Examples:**
    
    Regrid the time axes of field ``f`` conservatively onto a grid
    contained in field ``g``:
    
    >>> h = f.regridc(g, axes='T', 'conservative')
    
    Regrid the T axis of field ``f`` conservatively onto the grid
    specified in the dimension coordinate ``t``:
    
    >>> h = f.regridc({'T': t}, axes=('T'), 'conservative_1st')
    
    Regrid the T axis of field ``f`` using bilinear interpolation onto
    a grid contained in field ``g``:
    
    >>> h = f.regridc(g, axes=('T'), method='bilinear')
    
    Regrid the X and Y axes of field ``f`` conservatively onto a grid
    contained in field ``g``:
    
    >>> h = f.regridc(g, axes=('X','Y'), 'conservative_1st')
    
    Regrid the X and T axes of field ``f`` conservatively onto a grid
    contained in field ``g`` using the destination mask:
    
    >>> h = f.regridc(g, axes=('X','Y'), use_dst_mask=True, method='bilinear')

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'regridc', i=True) # pragma: no cover

        # Initialise ESMPy for regridding if found
        manager = Regrid.initialize()
        
        if inplace:
            f = self
        else:
            f = self.copy()

        # If dst is a dictionary set flag
        dst_dict = not isinstance(dst, f.__class__)
#        if isinstance(dst, self.__class__):
#            dst_dict = False
#            # If dst is a field list use the first field
#            if isinstance(dst, FieldList):
#                dst = dst[0]
#        else:
#            dst_dict = True
        
        # Get the number of axes
        if isinstance(axes, str):
            axes = (axes,)

        n_axes = len(axes)
        if n_axes < 1 or n_axes > 3:
            raise ValueError('Between 1 and 3 axes must be individually ' +
                             'specified.')
        
        # Retrieve the source axis keys and dimension coordinates
        src_axis_keys, src_coords = f._regrid_get_cartesian_coords('source', axes)
        
        # Retrieve the destination axis keys and dimension coordinates
        if dst_dict:
            dst_coords = []
            for axis in axes:
                try:
                    dst_coords.append(dst[axis])
                except KeyError:
                    raise ValueError('Axis ' + str(axis) +
                                     ' not specified in dst.')
            #--- End: for
            dst_axis_keys = None
        else:
            dst_axis_keys, dst_coords = \
                        dst._regrid_get_cartesian_coords('destination', axes)
        
        # Check that the units of the source and the destination
        # coords are equivalent and if so set the units of the source
        # coords to those of the destination coords
        for src_coord, dst_coord in zip(src_coords, dst_coords):
            if src_coord.Units.equivalent(dst_coord.Units):
                src_coord.units = dst_coord.units
            else:
                raise ValueError(
                    "Units of source and destination domains are not equivalent: {!r}, {!r}".format(
                        src_coord.Units, dst_coord.Units))
        #--- End: if

        # Get the axis indices and their order for the source field
        src_axis_indices, src_order = \
                        f._regrid_get_axis_indices(src_axis_keys)
        
        # Get the axis indices and their order for the destination field.
        if not dst_dict:
            dst_axis_indices, dst_order = \
                        dst._regrid_get_axis_indices(dst_axis_keys)

        # Pad out a single dimension with an extra one (see comments
        # in _regrid_check_bounds). Variables ending in _ext pertain
        # the extra dimension.
        axis_keys_ext = []
        coords_ext = []
        src_axis_indices_ext = src_axis_indices
        src_order_ext = src_order
        # Proceed if there is only one regridding dimension, but more than
        # one dimension to the field that is not of size one.
        if n_axes == 1 and f.squeeze().ndim > 1:
            # Find the length and index of the longest axis not including
            # the axis along which regridding will be performed.
            src_shape = numpy_array(f.shape)
            tmp = src_shape.copy()
            tmp[src_axis_indices] = -1
            max_length = -1
            max_ind = -1
            for ind, length in enumerate(tmp):
                if length > max_length:
                    max_length = length
                    max_ind = ind
            # If adding this extra dimension to the regridding axis will not
            # create sections that exceed 1 chunk of memory proceed to get
            # the coordinate and associated data for the extra dimension.
            if src_shape[src_axis_indices].prod()*max_length*8 < CHUNKSIZE():
                axis_keys_ext, coords_ext = \
                    f._regrid_get_cartesian_coords('source', [max_ind])
                src_axis_indices_ext, src_order_ext = \
                    f._regrid_get_axis_indices(axis_keys_ext + src_axis_keys)
        
        # Calculate shape of each regridded section
        shape = f._regrid_get_section_shape([coord.size for coord in coords_ext + dst_coords],
                                            src_axis_indices_ext)

        # Check the method
        f._regrid_check_method(method)

        # Check that use_src_mask is True for all methods other than
        # nearest_stod
        f._regrid_check_use_src_mask(use_src_mask, method)

        # Check that the regridding axes span two dimensions if using
        # higher order patch recovery
        if method == 'patch' and n_axes != 2:
            raise ValueError('Higher order patch recovery is only available ' +
                             'in 2D.')

        # Check the bounds of the coordinates
        f._regrid_check_bounds(src_coords, dst_coords, method,
                                  ext_coords=coords_ext)

        # Deal with case of 1D nonconservative regridding 
        nonconservative1D = False
        if (method not in ('conservative', 'conservative_1st', 'conservative_2nd')
            and n_axes == 1 and coords_ext == []):
            # Method is not conservative, regridding is to be done along
            # one dimension and that dimension has not been padded out with
            # an extra one.
            nonconservative1D = True
            coords_ext = [DimensionCoordinate(data=Data(
                [numpy_finfo('float32').epsneg, numpy_finfo('float32').eps]))]        

        # Section the data into slices of up to three dimensions getting a
        # list of reordered keys if required. Reordering on an extended axis
        # will not have any effect as all the items in the keys will be None.
        # Therefore it is only checked if the axes specified in axis_order are
        # in the regridding axes as this is informative to the user.
        section_keys, sections = f._regrid_get_reordered_sections(axis_order,
            src_axis_keys, src_axis_indices_ext)
        
        # Use bounds if the regridding method is conservative.
        use_bounds = f._regrid_use_bounds(method)
        
        # Retrieve the destination field's mask if appropriate
        dst_mask = None
        if not dst_dict and use_dst_mask and dst.data.ismasked:
            dst_mask = dst._regrid_get_destination_mask(dst_order,
                                                        cartesian=True,
                                                        coords_ext=coords_ext)
        
        # Create the destination ESMPy grid and fields
        dstgrid = Regrid.create_grid(coords_ext + dst_coords, use_bounds,
                                     mask=dst_mask, cartesian=True)
        dstfield = Regrid.create_field(dstgrid, 'dstfield')
        dstfracfield = Regrid.create_field(dstgrid, 'dstfracfield')
        
        # Regrid each section
        old_mask = None
        unmasked_grid_created = False
        for k in section_keys:
            d = sections[k]
            subsections = d.data.section(src_axis_indices_ext, chunks=True,
                                         min_step=2)
            for k2 in subsections.keys():
                d2 = subsections[k2]
                # Retrieve the source field's grid, create the ESMPy grid and a
                # handle to regridding.
                src_data = d2.squeeze().transpose(src_order_ext).array
                if nonconservative1D:
                    src_data = numpy_tile(src_data, (2,1))
                if (not (method == 'nearest_stod' and use_src_mask)
                    and numpy_ma_is_masked(src_data)):
                    mask = src_data.mask
                    if not numpy_array_equal(mask, old_mask):
                        # Release old memory
                        if old_mask is not None:
                            regridSrc2Dst.destroy()
                            srcfracfield.destroy()
                            srcfield.destroy()
                            srcgrid.destroy()

                        # (Re)create the source ESMPy grid and fields
                        srcgrid = Regrid.create_grid(coords_ext + src_coords,
                                                     use_bounds, mask=mask,
                                                     cartesian=True)
                        srcfield = Regrid.create_field(srcgrid, 'srcfield')
                        srcfracfield = Regrid.create_field(srcgrid,
                                                           'srcfracfield')
                        # (Re)initialise the regridder
                        regridSrc2Dst = Regrid(srcfield, dstfield, srcfracfield,
                                               dstfracfield, method=method,
                                               ignore_degenerate=ignore_degenerate)
                        old_mask = mask
                else:
                    if not unmasked_grid_created or old_mask is not None:
                        # Create the source ESMPy grid and fields
                        srcgrid = Regrid.create_grid(coords_ext + src_coords,
                                                     use_bounds, cartesian=True)
                        srcfield = Regrid.create_field(srcgrid, 'srcfield')
                        srcfracfield = Regrid.create_field(srcgrid,
                                                           'srcfracfield')
                        # Initialise the regridder
                        regridSrc2Dst = Regrid(srcfield, dstfield,
                                               srcfracfield,
                                               dstfracfield,
                                               method=method,
                                               ignore_degenerate=ignore_degenerate)
                        unmasked_grid_created = True
                        old_mask = None
                #--- End: if
                
                # Fill the source and destination fields
                f._regrid_fill_fields(src_data, srcfield, dstfield)
                
                # Run regridding
                dstfield = regridSrc2Dst.run_regridding(srcfield, dstfield)
                
                # Compute field mass if requested for conservative regridding
                if (_compute_field_mass is not None and method in
                    ('conservative', 'conservative_1st', 'conservative_2nd')):
                    f._regrid_compute_field_mass(_compute_field_mass,
                                                 k, srcgrid,
                                                 srcfield,
                                                 srcfracfield,
                                                 dstgrid, dstfield)
                
                # Get the regridded data or frac field as a numpy array
                regridded_data = f._regrid_get_regridded_data(method,
                                                              fracfield,
                                                              dstfield,
                                                              dstfracfield)
                
                if nonconservative1D:
                    # For nonconservative regridding along one dimension where that
                    # dimension has not been padded out take only one of the two
                    # rows of data as they should be nearly identical.
                    regridded_data = regridded_data[0]
                
                # Insert regridded data, with axes in correct order
                subsections[k2] = Data(
                    regridded_data.squeeze().transpose(src_order_ext).reshape(shape),
                    units=f.Units)
            #--- End: for
            sections[k] = Data.reconstruct_sectioned_data(subsections)
        #--- End: for
        
        # Construct new data from regridded sections
        new_data = Data.reconstruct_sectioned_data(sections)
        
        # Construct new field
#        if i:
#            f = self
#        else:
#            f = self.copy(_omit_Data=True)
#        #--- End:if
        
        ## Update ancillary variables of new field
        #f._conform_ancillary_variables(src_axis_keys, keep_size_1=False)
        
        # Update coordinate references of new field
        f._regrid_update_coordinate_references(dst, src_axis_keys,
                                               method, use_dst_mask,
                                               cartesian=True,
                                               axes=axes,
                                               n_axes=n_axes)
        
        # Update coordinates of new field
        f._regrid_update_coordinates(dst, dst_dict, dst_coords,
                                     src_axis_keys, dst_axis_keys,
                                     cartesian=True)
        
        # Copy across the destination fields coordinate references if necessary
        if not dst_dict:
            f._regrid_copy_coordinate_references(dst, dst_axis_keys)
        
        # Insert regridded data into new field
        f.set_data(new_data, axes=self.get_data_axes())
        
        # Release old memory
        regridSrc2Dst.destroy()
        dstfracfield.destroy()
        srcfracfield.destroy()
        dstfield.destroy()
        srcfield.destroy()
        dstgrid.destroy()
        srcgrid.destroy()
        
        return f

    
    def derivative(self, axis, wrap=None, one_sided_at_boundary=False,
                   inplace=False, i=False, cyclic=None):
        '''Return the derivative along the specified axis.

    The derivative is calculated by centred finite differences along
    the specified axis.

    If the axis is cyclic then the boundary is wrapped around,
    otherwise missing values are used at the boundary unless one-sided
    finite differences are requested.
    
    :Parameters:
    
        axis: 
            The axis , defined by that which would
            be selected by passing the given axis description to a
            call of the field's `domain_axis` method. For example, for
            a value of ``'X'``, the domain axis construct returned by
            ``f.domain_axis('X'))`` is selected.

        wrap: `bool`, optional
            If `True` then the boundary is wrapped around, otherwise the
            value of *one_sided_at_boundary* determines the boundary
            condition. If `None` then the cyclicity of the axis is
            autodetected.
    
        one_sided_at_boundary: `bool`, optional
            If `True` then one-sided finite differences are used at the
            boundary, otherwise missing values are used.
    
    
        inplace: `bool`, optional
            If `True` then do the operation in-place and return `None`.
    
        i: deprecated at version 3.0.0
            Use the *inplace* parameter instead.
    
    :Returns:
    
        `Field` or `None`
            TODO , or `None` if the operation was in-place.
    
    **Examples:**
    
    TODO

        '''
        if i:
            _DEPRECATION_ERROR_KWARGS(self, 'derivative', i=True) # pragma: no cover

        if cyclic:
            _DEPRECATION_ERROR_KWARGS(self, 'derivative', {'cyclic': cyclic},
                                      "Use the 'wrap' keyword instead") # pragma: no cover

        # Retrieve the axis
#        dims = self.dims(axis)
#        axis = self.domain_axis_key(axis, default=None)
        axis = self.domain_axis(axis, key=True, default=None)
        if axis is None:
            raise ValueError('Invalid axis specifier')
        
        dims = self.dimension_coordinates.filter_by_axis('exact', axis)
        len_dims = len(dims)
        if not len_dims:
            raise ValueError('Invalid axis specifier')
        elif len_dims != 1:
            raise ValueError('Axis specified is not unique.')

#        axis_key, coord = dict(dims).popitem()
        dckey, coord = dict(dims).popitem()

        # Get the axis index
        axis_index = self.get_data_axes().index(axis)

        # Automatically detect the cyclicity of the axis if cyclic is None
        if wrap is None:
            wrap = self.iscyclic(axis)

        # Set the boundary conditions
        if wrap:
            mode = 'wrap'
        elif one_sided_at_boundary:
            mode = 'nearest'
        else:
            mode = 'constant'

        if inplace:
            f = self
        else:
            f = self.copy()
            
        # Find the finite difference of the field
        f.convolution_filter([1, 0, -1], axis=axis, mode=mode,
                             update_bounds=False, inplace=True)

        # Find the finite difference of the axis
        d = convolve1d(coord, [1, 0, -1], mode=mode, cval=numpy_nan)
        if not cyclic and not one_sided_at_boundary:
            with numpy_errstate(invalid='ignore'):
                d = numpy_ma_masked_invalid(d)
        #--- End: if

        # Reshape the finite difference of the axis for broadcasting
        shape = [1] * self.ndim
        shape[axis_index] = d.size
        d = d.reshape(shape)

        # Find the derivative
        f.data /= Data(d, coord.units)

        # Update the standard name and long name
        standard_name = getattr(f, 'standard_name', None)
        long_name     = getattr(f, 'long_name', None)
        if standard_name is not None:
            del f.standard_name
            f.long_name = 'derivative of ' + standard_name
        elif long_name is not None:
            f.long_name = 'derivative of ' + long_name

        if inplace:
            f = None
        return f


    # ----------------------------------------------------------------
    # Aliases
    # ----------------------------------------------------------------
    def aux(self, identity, default=ValueError(), key=False, **kwargs):
        '''Alias for `cf.Field.auxiliary_coordinate`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'aux', kwargs,
                "Use methods of the 'auxiliary_coordinates' attribute instead.") # pragma: no cover

        return self.auxiliary_coordinate(identity, key=key, default=default)


    def auxs(self, *identities, **kwargs):
        '''Alias for `cf.Field.auxiliary_coordinates`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'auxs', kwargs,
                "Use methods of the 'auxiliary_coordinates' attribute instead.") # pragma: no cover
            
        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i:
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for
        
        return self.auxiliary_coordinates(*identities)
    

    def axis(self, identity, key=False, default=ValueError(), **kwargs):
        '''Alias of `cf.Field.domain_axis`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'axis', kwargs,
                                      "Use methods of the 'domain_axes' attribute instead.") # pragma: no cover

        return self.domain_axis(identity, key=key, default=default)
    

    def coord(self, identity, default=ValueError(), key=False,
              **kwargs):
        '''Alias for `cf.Field.coordinate`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'coord', kwargs,
                "Use methods of the 'coordinates' attribute instead.") # pragma: no cover
            
        if identity in self.domain_axes:
            # Allow an identity to be the domain axis construct key
            # spanned by a dimension coordinate construct
            return self.dimension_coordinate(identity, key=key, default=default)
    
        return self.coordinate(identity, key=key, default=default)


    def coords(self, *identities, **kwargs):
        '''Alias for `cf.Field.coordinates`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'coords', kwargs,
                                      "Use methods of the 'coordinates' attribute instead.")  # pragma: no cover
        

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i:
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for

        return self.coordinates.filter_by_identity(*identities)


    def dim(self, identity, default=ValueError(), key=False, **kwargs):
        '''Alias for `cf.Field.dimension_coordinate`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'dim', kwargs,
                "Use methods of the 'dimension_coordinates' attribute instead.") # pragma: no cover

        return self.dimension_coordinate(identity, key=key, default=default)


    def dims(self, *identities, **kwargs):
        '''Alias for `cf.Field.dimension_coordinates`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'dims', kwargs,
                "Use methods of the 'dimension_coordinates' attribute instead.") # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i:
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for

        return self.dimension_coordinates.filter_by_identity(*identities)


    def domain_anc(self, identity, default=ValueError(), key=False,
                   **kwargs):
        '''Alias for `cf.Field.domain_ancillary`.
        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'domain_anc', kwargs,
                                      "Use methods of the 'domain_ancillaries' attribute instead.") # pragma: no cover
        
        return self.domain_ancillary(identity, key=key, default=default)


    def domain_ancs(self, *identities, **kwargs):
        '''Alias for `cf.Field.domain_ancillaries`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'domain_ancs', kwargs,
                                      "Use methods of the 'domain_ancillaries' attribute instead.") # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i:
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for
        
        return self.domain_ancillaries.filter_by_identity(*identities)


    def field_anc(self, identity, default=ValueError(),  key=False, **kwargs):
        '''Alias for `cf.Field.field_ancillary`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'field_anc', kwargs,
                "Use methods of the 'field_ancillaries' attribute instead.") # pragma: no cover

        return self.field_ancillary(identity, key=key, default=default)


    def field_ancs(self, *identities, **kwargs):
        '''Alias for `cf.Field.field_ancillaries`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'field_ancs', kwargs,
                                      "Use methods of the 'field_ancillaries' attribute instead.") # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i:
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for
        
        return self.field_ancillaries.filter_by_identity(*identities)


    def item(self, identity, key=False, default=ValueError(), **kwargs):
        '''Alias for `cf.Field.construct``.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'item', kwargs,
                "Use methods of the 'constructs' attribute instead.") # pragma: no cover

        return self.construct(identity, key=key, default=default)


    def items(self, *identities, **kwargs):
        '''Alias for `c.Field.constructs.filter_by_data`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'items', kwargs,
                "Use methods of the 'constructs' attribute instead.") # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
        #--- End: for               

        return self.constructs.filter_by_data().filter_by_identity(*identities)
 

    def key(self, identity, default=ValueError(), **kwargs):
        '''Alias for `cf.Field.construct_key`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'key', kwargs,
                "Use 'construct' method or 'construct_key' method instead.") # pragma: no cover
        
        return self.construct_key(identity, default=default)


    def measure(self, identity, default=ValueError(), key=False,
                **kwargs):
        '''Alias for `cf.Field.cell_measure`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(
                self, 'measure', kwargs,
                "Use methods of the 'cell_measures' attribute instead") # pragma: no cover

        return self.cell_measure(identity, key=key, default=default)


    def measures(self, *identities, **kwargs):
        '''Alias for `cf.Field.cell_measures`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'measures', kwargs,
                                      "Use methods of the 'cell_measures' attribute instead") # pragma: no cover
            
        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
            try:
                if ':' in i and not i.startswith('measure:'):
                    _DEPRECATION_ERROR(
                        "The identity format {!r} has been deprecated. Use {!r} instead.".format(
                            i,  i.replace(':', '=', 1))) # pragma: no cover
            except TypeError:
                pass
        #--- End: for
        
        return self.cell_measures(*identities)


    def ref(self, identity, default=ValueError(),  key=False,  **kwargs):
        '''Alias for `cf.Field.coordinate_reference`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'ref', kwargs,
                                      "Use methods of the 'coordinate_references' attribute instead.") # pragma: no cover
        
        return self.coordinate_reference(identity, key=key, default=default)

    
    def refs(self, *identities, **kwargs):
        '''Alias for `cf.Field.coordinate_references`.

        '''
        if kwargs:
            _DEPRECATION_ERROR_KWARGS(self, 'refs', kwargs,
                                      "Use methods of the 'coordinate_references' attribute instead.") # pragma: no cover

        for i in identities:
            if isinstance(i, dict):
                _DEPRECATION_ERROR_DICT() # pragma: no cover
            elif isinstance(i, (list, tuple, set)):
                _DEPRECATION_ERROR_SEQUENCE(i) # pragma: no cover
        #--- End: for
        
        return self.coordinate_references(*identities)
    

    # ----------------------------------------------------------------
    # Deprecated attributes and methods
    # ----------------------------------------------------------------
    @property
    def _Axes(self):
        '''
        '''
        _DEPRECATION_ERROR_ATTRIBUTE(self, '_Axes', "Use attribute 'domain_axes' instead.") # pragma: no cover

        
    @property
    def CellMethods(self):
        '''
        '''
        _DEPRECATION_ERROR_ATTRIBUTE(self, 'CellMethods',
                                     "Use method 'cell_methods.ordered' instead.") # pragma: no cover
        

    @property
    def Items(self):
        '''Deprecated at version 3.0.0. Use attribute 'constructs' instead.

        '''
        _DEPRECATION_ERROR_ATTRIBUTE(
            self, 'Items',
            "Use 'constructs' attribute instead.") # pragma: no cover

    
    def CM(self, xxx):
        '''Deprecated at version 3.0.0

        '''
        _DEPRECATION_ERROR_METHOD(self, 'CM') # pragma: no cover


    def axis_name(self, *args, **kwargs):
        '''Return the canonical name for an axis.

    Deprecated at version 3.0.0. Use 'domain_axis_identity' method instead.

        ''' 
        _DEPRECATION_ERROR_METHOD(self, 'axis_name',
                                  "Use 'domain_axis_identity' method instead.") # pragma: no cover


    def data_axes(self):
        '''Return the domain axes for the data array dimensions.

    Deprecated at version 3.0.0. Use 'get_data_axes' method instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'data_axes',
            "Use 'get_data_axes' method instead.") # pragma: no cover


    def equivalent(self, other, rtol=None, atol=None, verbose=False):
        '''True if two fields are equivalent, False otherwise.

    Deprecated at version 3.0.0.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'equivalent')


    def expand_dims(self, position=0, axes=None, i=False, **kwargs):
        '''Insert a size 1 axis into the data array.

    Deprecated at version 3.0.0. Use 'insert_dimension' method instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'expand_dims',
            "Use 'insert_dimension' method instead.") # pragma: no cover


    def field(self, description=None, role=None, axes=None, axes_all=None,
              axes_subset=None, axes_superset=None, exact=False,
              inverse=False, match_and=True, ndim=None, bounds=False):
        '''Create an independent field from a domain item.

    Deprecated at version 3.0.0. Use 'convert' method instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'field',
                                  "Use 'convert' method instead.") # pragma: no cover


    def HDF_chunks(self, *chunksizes):
        '''Deprecated at version 3.0.0. Use methods 'Data.nc_hdf5_chunksizes',
    'Data.nc_set_hdf5_chunksizes', 'Data.nc_clear_hdf5_chunksizes'
    instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'HDF_chunks',
            "Use methods 'Data.nc_hdf5_chunksizes', 'Data.nc_set_hdf5_chunksizes', 'Data.nc_clear_hdf5_chunksizes' instead.") # pragma: no cover

    
    def insert_measure(self, item, key=None, axes=None, copy=True, replace=True):
        '''Insert a cell measure object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_measure',
                                  "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_dim(self, item, key=None, axes=None, copy=True, replace=True):
        '''Insert a dimension coordinate object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_dim',
                                  "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_axis(self, axis, key=None, replace=True):
        '''Insert a domain axis into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_axis', 
                                  "Use method 'set_construct' instead.") # pragma: no cover    


    def insert_item(self, role, item, key=None, axes=None,
                    copy=True, replace=True):
        '''Insert an item into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_item',
                                  "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_aux(self, item, key=None, axes=None, copy=True, replace=True):
        '''Insert an auxiliary coordinate object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_aux', "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_cell_methods(self, item):
        '''Insert one or more cell method objects into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_cell_methods',
                                  "Use method 'set_construct' instead.") # pragma: no cover


    def insert_domain_anc(self, item, key=None, axes=None, copy=True,
                          replace=True):
        '''Insert a domain ancillary object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.
        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_domain_anc',
                                  "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_data(self, data, axes=None, copy=True, replace=True):
        '''Insert a data array into the field.

    Deprecated at version 3.0.0. Use method 'set_data' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_data',
                                  "Use method 'set_data' instead.") # pragma: no cover


    def insert_field_anc(self, item, key=None, axes=None, copy=True,
                         replace=True):
        '''Insert a field ancillary object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' instead.g

        '''
        _DEPRECATION_ERROR_METHOD(self, 'insert_field_anc',
                                  "Use method 'set_construct' instead.")  # pragma: no cover


    def insert_ref(self, item, key=None, axes=None, copy=True, replace=True):
        '''Insert a coordinate reference object into the field.

    Deprecated at version 3.0.0. Use method 'set_construct' or
    'set_coordinate_reference' instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'insert_ref',
            "Use method 'set_construct' or 'set_coordinate_reference' instead.")  # pragma: no cover

    
    def item_axes(self, description=None, role=None, axes=None,
                  axes_all=None, axes_subset=None, axes_superset=None,
                  exact=False, inverse=False, match_and=True,
                  ndim=None, default=None):
        '''Return the axes of a domain item of the field.

    Deprecated at version 3.0.0. Use the 'get_data_axes' method instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'item_axes',
            "Use method 'get_data_axes' instead.") # pragma: no cover


    def items_axes(self, description=None, role=None, axes=None,
                   axes_all=None, axes_subset=None, axes_superset=None,
                   exact=False, inverse=False, match_and=True,
                   ndim=None):
        '''Return the axes of items of the field.

    Deprecated at version 3.0.0. Use the 'data_axes' method of
    attribute 'constructs' instead.

        '''    
        _DEPRECATION_ERROR_METHOD(
            self, 'items_axes',
            "Use the 'data_axes' method of attribute 'constructs' instead.") # pragma: no cover


    def key_item(self, identity, default=ValueError(), **kwargs):
        '''Return an item, or its identifier, from the field.

    Deprecated at version 3.0.0

        '''
        _DEPRECATION_ERROR_METHOD(self, 'key_item')


    def new_identifier(self, item_type):
        '''Return a new, unused construct key.

    Deprecated at version 3.0.0. Use 'new_identifier' method of
    'constructs' attribute instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, ' new_identifier', 
            "Use 'new_identifier' method of 'constructs' attribute instead.") # pragma: no cover    


    def remove_item(self, description=None, role=None, axes=None,
                    axes_all=None, axes_subset=None,
                    axes_superset=None, ndim=None, exact=False,
                    inverse=False, match_and=True, key=False):
        '''Remove and return an item from the field.

    Deprecated at version 3.0.0. Use `del_construct` method instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'remove_item',
                                  "Use method 'del_construct' instead.") # pragma: no cover


    def remove_items(self, description=None, role=None, axes=None,
                     axes_all=None, axes_subset=None,
                     axes_superset=None, ndim=None, exact=False,
                     inverse=False, match_and=True):
        '''Remove and return items from the field.

    Deprecated at version 3.0.0. Use `del_construct` method instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'remove_items',
                                  "Use method 'del_construct' instead.") # pragma: no cover


    def remove_axes(self, axes=None, **kwargs):
        '''Remove and return axes from the field.

    Deprecated at version 3.0.0. Use method 'del_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'remove_axes',
                                  "Use method 'del_construct' instead.")  # pragma: no cover


    def remove_axis(self, axes=None, size=None, **kwargs):
        '''Remove and return a unique axis from the field.

    Deprecated at version 3.0.0. Use method 'del_construct' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'remove_axis',
                                  "Use method 'del_construct' instead.") # pragma: no cover


    def remove_data(self, default=ValueError()):
        '''Remove and return the data array.

    Deprecated at version 3.0.0. Use method 'del_data' instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'remove_data',
                                  "Use method 'del_data' instead.") # pragma: no cover


    def transpose_item(self, description=None, iaxes=None, **kwargs):
        '''Permute the axes of a field item data array.

    Deprecated at version 3.0.0. Use method 'transpose_construct'
    instead.

        '''
        _DEPRECATION_ERROR_METHOD(self, 'transpose_item',
                                  "Use method 'transpose_construct' instead.") # pragma: no cover


    def unlimited(self, *args):
        '''Deprecated at version 3.0.0. Use methods
    `DomainAxis.nc_is_unlimited`, and `DomainAxis.nc_set_unlimited`
    instead.

        '''
        _DEPRECATION_ERROR_METHOD(
            self, 'unlimited',
            "Use methods 'DomainAxis.nc_is_unlimited', and 'DomainAxis.nc_set_unlimited' instead.") # pragma: no cover

        
#--- End: class


# ====================================================================
#
# SubspaceField object
#
# ====================================================================

class SubspaceField(mixin.Subspace):
    '''Return a subspace of a field.

A subspace may be defined in "domain-space" via data array values of
its domain items: dimension coordinate, auxiliary coordinate, cell
measure, domain ancillary and field ancillary objects.

Alternatively, a subspace my be defined be in "index-space" via
explicit indices for the data array using an extended Python slicing
syntax.

Subspacing by values of 1-d coordinates allows a subspaced field to be
defined via coordinate values of its domain. The benefits of
subspacing in this fashion are:

  * The axes to be subspaced may identified by name.
  * The position in the data array of each axis need not be known and
    the axes to be subspaced may be given in any order.
  * Axes for which no subspacing is required need not be specified.
  * Size 1 axes in the subspaced field are always retained, but may be
    subsequently removed with the `~cf.Field.squeeze` method.

  * Size 1 axes of the domain which are not spanned by the data array
    may be specified.

Metadata values are provided as keyword arguments. Metadata items are
identified by their identity or their axis's identifier in the field.

``f.subspace(*args, **kwargs)`` is equivalent to ``f[f.indices(*args,
**kwargs)]``. See `cf.Field.indices` for details.

.. seealso:: `__getitem__`, `indices`, `where`

**Examples:**

>>> f,shape
(12, 73, 96)
>>> f.subspace().shape
(12, 73, 96)
>>> f.subspace(latitude=0).shape
(12, 1, 96)
>>> f.subspace(latitude=cf.wi(-30, 30)).shape
(12, 25, 96)
>>> f.subspace(long=cf.ge(270, 'degrees_east'), lat=cf.set([0, 2.5, 10])).shape
(12, 3, 24)
>>> f.subspace(latitude=cf.lt(0, 'degrees_north'))
(12, 36, 96)
>>> f.subspace(latitude=[cf.lt(0, 'degrees_north'), 90])
(12, 37, 96)
>>> import math
>>> f.subspace('exact', longitude=cf.lt(math.pi, 'radian'), height=2)
(12, 73, 48)
>>> f.subspace(height=cf.gt(3))
IndexError: No indices found for 'height' values gt 3
>>> f.subspace(dim2=3.75).shape
(12, 1, 96)
>>> f.subspace(time=cf.le(cf.dt('1860-06-16 12:00:00')).shape
(6, 73, 96)
>>> f.subspace(time=cf.gt(cf.dt(1860, 7)),shape
(5, 73, 96)

Note that if a comparison function (such as `cf.wi`) does not specify
any units, then the units of the named item are assumed.

    '''
        
    __slots__ = []

    def __call__(self, *args, **kwargs):
        '''Return a subspace of the field defined by coordinate values.
    
    :Parameters:
    
        kwargs: *optional*
            Keyword names identify coordinates; and keyword values specify
            the coordinate values which are to be reinterpreted as indices
            to the field's data array.
    
    
    ~~~~~~~~~~~~~~ /??????
            Coordinates are identified by their exact identity or by their
            axis's identifier in the field's domain.
    
            A keyword value is a condition, or sequence of conditions,
            which is evaluated by finding where the coordinate's data
            array equals each condition. The locations where the
            conditions are satisfied are interpreted as indices to the
            field's data array. If a condition is a scalar ``x`` then
            this is equivalent to the `Query` object ``cf.eq(x)``.
    
    :Returns:
    
        `Field`
    TODO
    
    **Examples:**
    
    >>> f.indices(lat=0.0, lon=0.0)
    >>> f.indices(lon=cf.lt(0.0), lon=cf.set([0, 3.75]))
    >>> f.indices(lon=cf.lt(0.0), lon=cf.set([0, 356.25]))
    >>> f.indices(lon=cf.lt(0.0), lon=cf.set([0, 3.75, 356.25]))

        '''
        field = self.variable

        if not args and not kwargs:
            return field.copy()    

        return field[field.indices(*args, **kwargs)]


    def __getitem__(self, indices):
        '''Called to implement evaluation of x[indices].

    x.__getitem__(indices) <==> x[indices]
    
    Returns a subspace of a field.

        '''
        return super().__getitem__(indices)


    def __setitem__(self, indices, value):
        '''Called to implement assignment to x[indices]

    x.__setitem__(indices, value) <==> x[indices]

        '''      
        super().__setitem__(indices, value)


#--- End: class


#class FieldList_old(list):
#    '''An ordered sequence of fields.
#
#Each element of a field list is a field construct.
#
#A field list supports the python list-like operations (such as
#indexing and methods like `!append`).
#
#>>> fl = cf.FieldList()
#>>> len(fl)
#0
#>>> f
#<CF Field: air_temperaturetime(12), latitude(73), longitude(96) K>
#>>> fl = cf.FieldList(f)
#>>> len(fl)
#1
#>>> fl = cf.FieldList([f, f])
#>>> len(fl)
#2
#>>> fl = cf.FieldList(cf.FieldList([f] * 3))
#>>> len(fl)
#3
#>>> len(fl + fl)
#6
#
#These methods provide functionality similar to that of a
#:ref:`built-in list <python:tut-morelists>`. The main difference is
#that when a field element needs to be assesed for equality its
#`~cf.Field.equals` method is used, rather than the ``==`` operator.
#
#    '''   
#    def __init__(self, fields=None):
#        '''**Initialization**
#
#:Parameters:
#
#    fields: (sequence of) `Field`, optional
#         Create a new field list with these fields.
#
#        '''
#        if fields is not None:
#            if isinstance(fields, Field):
#                self.append(fields)
#            else:
#                self.extend(fields)         
#    #--- End: def
#
#    def __call__(self, *identities):
#        '''TODO'''        
#        return self.filter_by_identity(*identities)
#    #--- End: def
#    
#    def __repr__(self):
#        '''Called by the `repr` built-in function.
#
#x.__repr__() <==> repr(x)
#
#        '''
#        
#        out = [repr(f) for f in self]
#        out = ',\n '.join(out)
#        return '['+out+']'
#    #--- End: def
#
##    def __str__(self):
##        '''Called by the `str` built-in function.
##
##x.__str__() <==> str(x)
##
##        '''
##        return '\n'.join(str(f) for f in self)
##    #--- End: def
#
#    # ----------------------------------------------------------------
#    # Overloaded list methods
#    # ----------------------------------------------------------------
#    def __add__(self, x):
#        '''Called to implement evaluation of f + x
#
#f.__add__(x) <==> f + x
#
#:Returns:
#
#    `FieldList`
#
#**Examples:**
#
#>>> h = f + g
#>>> f += g
#
#        '''
#        return type(self)(list.__add__(self, x))
#    #--- End: def
#
#    def __mul__(self, x):
#        '''Called to implement evaluation of f * x
#
#f.__mul__(x) <==> f * x
#
#:Returns:
#
#    `FieldList`
#
#**Examples:**
#
#>>> h = f * 2
#>>> f *= 2
#
#        '''
#        return type(self)(list.__mul__(self, x))
#    #--- End: def
#
#    def __getslice__(self, i, j):
#        '''Called to implement evaluation of f[i:j]
#
#    f.__getslice__(i, j) <==> f[i:j]
#    
#    :Returns:
#    
#        `FieldList`
#    
#    **Examples:**
#    
#    >>> g = f[0:1]
#    >>> g = f[1:-4]
#    >>> g = f[:1]
#    >>> g = f[1:]
#
#        '''
#        return type(self)(list.__getslice__(self, i, j))
#
#
#    def __getitem__(self, index):
#        '''Called to implement evaluation of f[index]
#
#    f.__getitem_(index) <==> f[index]
#    
#    :Returns:
#    
#        `Field` or `FieldList`
#            If *index* is an integer then a field construct is
#            returned. If *index* is a slice then a field list is returned,
#            which may be empty.
#    
#    **Examples:**
#    
#    >>> g = f[0]
#    >>> g = f[-1:-4:-1]
#    >>> g = f[2:2:2]
#
#        '''
#        out = list.__getitem__(self, index)
#
#        if isinstance(out, list):
#            return type(self)(out)
#
#        return out
#
#    # ???
#    __len__     = list.__len__
#    __setitem__ = list.__setitem__    
#    append      = list.append
#    extend      = list.extend
#    insert      = list.insert
#    pop         = list.pop
#    reverse     = list.reverse
#    sort        = list.sort
#
#    def __contains__(self, y):
#        '''Called to implement membership test operators.
#
#x.__contains__(y) <==> y in x
#
#Each field in the field list is compared with the field's
#`~cf.Field.equals` method, as aopposed to the ``==`` operator.
#
#Note that ``y in fl`` is equivalent to ``any(f.equals(y) for f in fl)``.
#
#        '''
#        for f in self:
#            if f.equals(y):
#                return True
#        #--- End: for
#            
#        return False
#    #--- End: def
#
#    def close(self):
#        '''Close all files referenced by each field.
#
#Note that a closed file will be automatically reopened if its contents
#are subsequently required.
#
#:Returns:
#
#    `None`
#
#**Examples:**
#
#>>> f.close()
#
#        '''
#        for f in self:
#            f.close()
#    #--- End: def
#
#    def count(self, value):
#        '''Return number of occurrences of value
#
#Each field in the field list is compared with the field's
#`~cf.Field.equals` method, as opposed to the ``==`` operator.
#
#Note that ``fl.count(value)`` is equivalent to ``sum(f.equals(value)
#for f in fl)``.
#
#.. seealso:: `cf.Field.equals`, `list.count`
#
#**Examples:**
#
#>>> f = cf.FieldList([a, b, c, a])
#>>> f.count(a)
#2
#>>> f.count(b)
#1
#>>> f.count(a+1)
#0
#
#        '''
#        return len([None for f in self if f.equals(value)])
#    #--- End def
#
#    def index(self, value, start=0, stop=None):
#        '''Return first index of value.
#
#Each field in the field list is compared with the field's
#`~cf.Field.equals` method, as aopposed to the ``==`` operator.
#
#It is an error if there is no such field.
#
#.. seealso:: `list.index`
#
#**Examples:**
#
#        '''      
#        if start < 0:
#            start = len(self) + start
#
#        if stop is None:
#            stop = len(self)
#        elif stop < 0:
#            stop = len(self) + stop
#
#        for i, f in enumerate(self[start:stop]):
#            if f.equals(value):
#               return i + start
#        #--- End: for
#
#        raise ValueError(
#            "{0!r} is not in {1}".format(value, self.__class__.__name__))
#    #--- End: def
#
#    # 0
#    def remove(self, value):
#        '''Remove first occurrence of value.
#
#Each field in the field list is compared with its `~cf.Field.equals`
#method, as opposed to the ``==`` operator.
#
#.. seealso:: `list.remove`
#
#        '''
#        for i, f in enumerate(self):
#            if f.equals(value):
#                del self[i]
#                return
#        #--- End: for
#        
#        raise ValueError(
#            "{0}.remove(x): x not in {0}".format(self.__class__.__name__))
#    #--- End: def
#
#
#    def sort(self, key=None, reverse=False):
#        '''Sort of the field list in place.
#
#    By default the field list is sorted by the identities of its field
#    construct elements.
#
#    The sort is stable.
#    
#    .. versionadded:: 1.0.4
#    
#    .. seealso:: `reverse`
#    
#    :Parameters:
#    
#        key: function, optional
#            Specify a function of one argument that is used to extract
#            a comparison key from each field construct. By default the
#            field list is sorted by field identity, i.e. the default
#            value of *key* is ``lambda f: f.identity()``.
#    
#        reverse: `bool`, optional
#            If set to `True`, then the field list elements are sorted
#            as if each comparison were reversed.
#    
#    :Returns:
#    
#        `None`
#    
#    **Examples:**
#    
#    >>> fl
#    [<CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
#     <CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>,
#     <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>,
#     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>]
#    >>> fl.sort()
#    >>> fl
#    [<CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>,
#     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
#     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
#     <CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>]
#    >>> fl.sort(reverse=True)
#    >>> fl
#    [<CF Field: ocean_meridional_overturning_streamfunction(time(12), region(4), depth(40), latitude(180)) m3 s-1>,
#     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
#     <CF Field: eastward_wind(time(3), air_pressure(5), grid_latitude(110), grid_longitude(106)) m s-1>,
#     <CF Field: air_temperature(time(12), latitude(64), longitude(128)) K>]
#    
#    >>> [f.datum(0) for f in fl]
#    [masked,
#     -0.12850454449653625,
#     -0.12850454449653625,
#     236.51275634765625]
#    >>> fl.sort(key=lambda f: f.datum(0), reverse=True)
#    >>> [f.datum(0) for f in fl]
#    [masked,
#     236.51275634765625,
#     -0.12850454449653625,
#     -0.12850454449653625]
#    
#    >>> from operator import attrgetter
#    >>> [f.long_name for f in fl]
#    ['Meridional Overturning Streamfunction',
#     'U COMPNT OF WIND ON PRESSURE LEVELS',
#     'U COMPNT OF WIND ON PRESSURE LEVELS',
#     'air_temperature']
#    >>> fl.sort(key=attrgetter('long_name'))
#    >>> [f.long_name for f in fl]
#    ['air_temperature',
#     'Meridional Overturning Streamfunction',
#     'U COMPNT OF WIND ON PRESSURE LEVELS',
#     'U COMPNT OF WIND ON PRESSURE LEVELS']
#
#        '''
#        if key is None:
#            key = lambda f: f.identity()
#            
#        return super().sort(key=key, reverse=reverse)
#
#
#
#    def _deepcopy__(self, memo):
#        '''Called by the `copy.deepcopy` standard library function.
#
#        '''
#        return self.copy()
#
#    
#    def concatenate(self, axis=0, _preserve=True):
#        '''Join the sequence of fields together.
#
#    This is different to `cf.aggregate` because it does not account
#    for all metadata. For example, it assumes that the axis order is
#    the same in each field.
#    
#    .. versionadded:: 1.0
#    
#    .. seealso:: `cf.aggregate`, `Data.concatenate`
#    
#    :Parameters:
#    
#        axis: `int`, optional
#            TODO
#
#    :Returns:
#    
#        `Field`
#            TODO
#
#        '''
#        return self[0].concatenate(self, axis=axis, _preserve=_preserve)
#
#
#    def copy(self, data=True):
#        '''Return a deep copy.
#    
#    ``f.copy()`` is equivalent to ``copy.deepcopy(f)``.
#    
#    :Returns:
#    
#            The deep copy.
#    
#    **Examples:**
#    
#    >>> g = f.copy()
#    >>> g is f
#    False
#    >>> f.equals(g)
#    True
#    >>> import copy
#    >>> h = copy.deepcopy(f)
#    >>> h is f
#    False
#    >>> f.equals(g)
#    True
#
#        '''
#        return type(self)([f.copy(data=data) for f in self])
#
#    
#    def equals(self, other, rtol=None, atol=None, verbose=False,
#               ignore_data_type=False, ignore_fill_value=False,
#               ignore_properties=(), ignore_compression=False,
#               ignore_type=False, ignore=(), traceback=False,
#               unordered=False):
#        '''Whether two field lists are the same.
#
#    Equality requires the two field lists to have the same length and
#    for the the field construct elements to be equal pair-wise, using
#    their `~cf.Field.equals` methods.
#    
#    Any type of object may be tested but, in general, equality is only
#    possible with another field list, or a subclass of one. See the
#    *ignore_type* parameter.
#    
#    Equality is between teo field constructs is strict by
#    default. This means that for two field constructs to be considered
#    equal they must have corresponding metadata constructs and for
#    each pair of constructs:
#    
#    * the same descriptive properties must be present, with the same
#      values and data types, and vector-valued properties must also
#      have same the size and be element-wise equal (see the
#      *ignore_properties* and *ignore_data_type* parameters), and
#    
#    ..
#    
#    * if there are data arrays then they must have same shape and data
#      type, the same missing data mask, and be element-wise equal (see
#      the *ignore_data_type* parameter).
#    
#    Two real numbers ``x`` and ``y`` are considered equal if
#    ``|x-y|<=atol+rtol|y|``, where ``atol`` (the tolerance on absolute
#    differences) and ``rtol`` (the tolerance on relative differences)
#    are positive, typically very small numbers. See the *atol* and
#    *rtol* parameters.
#    
#    If data arrays are compressed then the compression type and the
#    underlying compressed arrays must be the same, as well as the
#    arrays in their uncompressed forms. See the *ignore_compression*
#    parameter.
#    
#    NetCDF elements, such as netCDF variable and dimension names, do
#    not constitute part of the CF data model and so are not checked on
#    any construct.
#    
#    :Parameters:
#        other: 
#            The object to compare for equality.
#    
#        atol: float, optional
#            The tolerance on absolute differences between real
#            numbers. The default value is set by the `cfdm.ATOL`
#            function.
#            
#        rtol: float, optional
#            The tolerance on relative differences between real
#            numbers. The default value is set by the `cfdm.RTOL`
#            function.
#    
#        ignore_fill_value: `bool`, optional
#            If `True` then the "_FillValue" and "missing_value"
#            properties are omitted from the comparison, for the field
#            construct and metadata constructs.
#    
#        verbose: `bool`, optional
#            If `True` then print information about differences that lead
#            to inequality.
#    
#        ignore_properties: sequence of `str`, optional
#            The names of properties of the field construct (not the
#            metadata constructs) to omit from the comparison. Note
#            that the "Conventions" property is always omitted by
#            default.
#    
#        ignore_data_type: `bool`, optional
#            If `True` then ignore the data types in all numerical
#            comparisons. By default different numerical data types
#            imply inequality, regardless of whether the elements are
#            within the tolerance for equality.
#    
#        ignore_compression: `bool`, optional
#            If `True` then any compression applied to underlying arrays
#            is ignored and only uncompressed arrays are tested for
#            equality. By default the compression type and, if
#            applicable, the underlying compressed arrays must be the
#            same, as well as the arrays in their uncompressed forms
#    
#        ignore_type: `bool`, optional
#            Any type of object may be tested but, in general, equality
#            is only possible with another field list, or a subclass of
#            one. If *ignore_type* is True then
#            ``FieldList(source=other)`` is tested, rather than the
#            ``other`` defined by the *other* parameter.
#
#        unordered: `bool`, optional
#            TODO
#    
#    :Returns: 
#      
#        `bool`
#            Whether the two field lists are equal.
#    
#    **Examples:**
#    
#    >>> fl.equals(fl)
#    True
#    >>> fl.equals(fl.copy())
#    True
#    >>> fl.equals(fl[:])
#    True
#    >>> fl.equals('not a FieldList instance')
#    False
#
#        '''
#        if traceback:
#            _DEPRECATION_ERROR_KWARGS(self, 'equals', traceback=True) # pragma: no cover
#            
#        if ignore:
#            _DEPRECATION_ERROR_KWARGS(self, 'equals', {'ignore': ignore},
#                                      "Use keyword 'ignore_properties' instead.") # pragma: no cover
#            
#        # Check for object identity
#        if self is other:
#            return True
#
#        # Check that each object is of compatible type
#        if ignore_type:
#            if not isinstance(other, self.__class__):
#                other = type(self)(source=other, copy=False)
#        elif not isinstance(other, self.__class__):
#            if verbose:
#                print("{0}: Incompatible type: {1}".format(
#		    self.__class__.__name__, other.__class__.__name__)) # pragma: no cover
#            return False
#
#        # Check that there are equal numbers of fields
#        len_self = len(self)
#        if len_self != len(other): 
#            if verbose:
#                print("{0}: Different numbers of field construct: {1}, {2}".format(
#		    self.__class__.__name__,
#		    len_self, len(other))) # pragma: no cover
#            return False
#
#        if not unordered or len_self == 1:
#       	    # ----------------------------------------------------
#    	    # Check the lists pair-wise
#    	    # ----------------------------------------------------
#    	    for i, (f, g) in enumerate(zip(self, other)):
#    	        if not f.equals(g, rtol=rtol, atol=atol,
#                                ignore_fill_value=ignore_fill_value,
#                                ignore_properties=ignore_properties,
#                                ignore_compression=ignore_compression,
#                                ignore_data_type=ignore_data_type,
#                                ignore_type=ignore_type,
#                                verbose=verbose):
#                    if verbose:
#                        print("{0}: Different field constructs at element {1}: {2!r}, {3!r}".format(
#    			    self.__class__.__name__, i, f, g)) # pragma: no cover
#                    return False
#        else:
#    	    # ----------------------------------------------------
#    	    # Check the lists set-wise
#    	    # ----------------------------------------------------
#    	    # Group the variables by identity
#            self_identity = {}
#            for f in self:
#                self_identity.setdefault(f.identity(), []).append(f)
#
#            other_identity = {}
#            for f in other:
#                other_identity.setdefault(f.identity(), []).append(f)
#
#    	    # Check that there are the same identities
#            if set(self_identity) != set(other_identity):
#    	        if verbose:
#                    print("{}: Different sets of identities: {}, {}".format(
#    			self.__class__.__name__,
#    			set(self_identity),
#    			set(other_identity))) # pragma: no cover
#    	        return False
#
#            # Check that there are the same number of variables
#    	    # for each identity
#            for identity, fl in self_identity.items():
#    	        gl = other_identity[identity]
#    	        if len(fl) != len(gl):
#                    if verbose:
#                        print("{0}: Different numbers of {1!r} {2}s: {3}, {4}".format(
#    			    self.__class__.__name__,
#    			    identity,
#                            fl[0].__class__.__name__,
#    			    len(fl), len(gl))) # pragma: no cover
#                    return False
#            #--- End: for
#
#    	    # For each identity, check that there are matching pairs
#            # of equal fields.
#            for identity, fl in self_identity.items():
#                gl = other_identity[identity]
#
#                for f in fl:
#                    found_match = False
#                    for i, g in enumerate(gl):
#                        if f.equals(g, rtol=rtol, atol=atol,
#                                    ignore_fill_value=ignore_fill_value,
#                                    ignore_properties=ignore_properties,
#                                    ignore_compression=ignore_compression,
#                                    ignore_data_type=ignore_data_type,
#                                    ignore_type=ignore_type,
#                                    verbose=verbose):
#                            found_match = True
#                            del gl[i]
#                            break
#                #--- End: for
#                
#                if not found_match:
#                    if verbose:                        
#                        print("{0}: No {1} equal to: {2!r}".format(
#    			    self.__class__.__name__, g.__class__.__name__, f)) # pragma: no cover
#                    return False
#        #--- End: if
#
#        # ------------------------------------------------------------
#    	# Still here? Then the field lists are equal
#    	# ------------------------------------------------------------
#        return True	    
#
#
#    def select(self, *identities, **kwargs):
#        '''Select field constructs by identity.
#
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match` method of the field constucts. For example, to
#    select all field constructs whose identity is *not*
#    ``'air_temperature'``:
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match('air_temperature'))
#    
#    `select` is an alias of `filter_by_identity`.
#    
#    .. seealso:: `filter_by_identity`, `filter_by_units`,
#                 `filter_by_construct`, `filter_by_naxes`,
#                 `filter_by_rank`, `filter_by_property`
#    
#        identities: optional
#            Select field constructs. By default all field constructs
#            are selected. May be one or more of:
#    
#              * The identity of a field construct.
#    
#            A construct identity is specified by a string
#            (e.g. ``'air_temperature'``, ``'long_name=Air
#            Temperature', ``'ncvar%tas'``, etc.); or a compiled
#            regular expression (e.g. ``re.compile('^air_')``) that
#            selects the relevant constructs whose identities match via
#            `re.search`.
#    
#            Each construct has a number of identities, and is selected
#            if any of them match any of those provided. A construct's
#            identities are those returned by its `!identities`
#            method. In the following example, the construct ``x`` has
#            five identities:
#    
#               >>> x.identities()
#               ['air_temperature', 'long_name=Air Temperature', 'foo=bar', 'standard_name=air_temperature', 'ncvar%tas']
#    
#            Note that in the output of a `print` call or `!dump`
#            method, a construct is always described by one of its
#            identities, and so this description may always be used as
#            an *identities* argument.
#    
#        kwargs: deprecated at version 3.0.0
#                  
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    TODO
#
#        '''
#        if kwargs:
#            _DEPRECATION_ERROR_KWARGS(
#                self, 'select', kwargs,
#                "Use methods 'filter_by_units',  'filter_by_construct', 'filter_by_properties', 'filter_by_naxes', 'filter_by_rank' instead.") # pragma: no cover
#
#        if identities and isinstance(identities[0], (list, tuple, set)):
#            _DEPRECATION_ERROR(
#                "Use of a {!r} for identities has been deprecated. Use the * operator to unpack the arguments instead.".format(
#                identities[0].__class__.__name__)) # pragma: no cover
#
#        for i in identities:
#            if isinstance(i, dict):
#                _DEPRECATION_ERROR_DICT(
#                    "Use methods 'filter_by_units', 'filter_by_construct', 'filter_by_properties', 'filter_by_naxes', 'filter_by_rank' instead.") # pragma: no cover
#            try:
#                if ':' in i:
#                    new = i.replace(':', '=', 1)
#                    _DEPRECATION_ERROR(
#                        "The ':' format has been deprecated. Use {!r} instead.".format(new)) # pragma: no cover
#            except TypeError:
#                pass
#        #--- End: for
#        
#        return self.filter_by_identity(*identities)
#
#
#
#    def filter_by_construct(self, *mode, **constructs):
#        '''TODO
#
#        '''    
#        return type(self)(f for f in self if f.match_by_construct(*mode, **constructs))
#
#    
#    def filter_by_identity(self, *identities):
#        '''Select field constructs by identity.
#
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match_by_identity` method of the field constucts. For
#    example, to select all field constructs whose identity is *not*
#    ``'air_temperature'``:
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match_by_identity('air_temperature'))
#    
#    `select` is an alias of `filter_by_identity`.
#    
#    .. versionadded:: 3.0.0
#    
#    .. seealso:: `select`, `filter_by_units`, `filter_by_construct`,
#                 `filter_by_naxes`, `filter_by_rank`,
#                 `filter_by_property`
#    
#        identities: optional
#            Select field constructs. By default all field constructs
#            are selected. May be one or more of:
#    
#              * The identity of a field construct.
#    
#            A construct identity is specified by a string (e.g.
#            ``'air_temperature'``, ``'long_name=Air Temperature',
#            ``'ncvar%tas'``, etc.); or a compiled regular expression
#            (e.g. ``re.compile('^air_')``) that selects the relevant
#            constructs whose identities match via `re.search`.
#    
#            Each construct has a number of identities, and is selected
#            if any of them match any of those provided. A construct's
#            identities are those returned by its `!identities`
#            method. In the following example, the construct ``x`` has
#            five identities:
#    
#               >>> x.identities()
#               ['air_temperature', 'long_name=Air Temperature', 'foo=bar', 'standard_name=air_temperature', 'ncvar%tas']
#    
#            Note that in the output of a `print` call or `!dump`
#            method, a construct is always described by one of its
#            identities, and so this description may always be used as
#            an *identities* argument.
#    
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    TODO
#
#        '''       
#        return type(self)(f for f in self if f.match_by_identity(*identities))
#
#    
#    def filter_by_naxes(self, *naxes):
#        '''Select field constructs by property.
#
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match_by_naxes` method of the field constucts. For
#    example, to select all field constructs which do *not* have
#    3-dimensional data:
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match_by_naxes(3))
#    
#    .. versionadded:: 3.0.0
#    
#    .. seealso:: `select`, `filter_by_identity`,
#                 `filter_by_construct`, `filter_by_property`,
#                 `filter_by_rank`, `filter_by_units` :Parameters:
#    
#        naxes: optional
#            Select field constructs whose data spans a particular
#            number of domain axis constructs.
#    
#            A number of domain axis constructs is given by an `int`.
#    
#            If no numbers are provided then all field constructs are
#            selected.
#         
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    TODO
#
#        '''
#        return type(self)(f for f in self if f.match_by_naxes(*naxes))
#
#    
#    def filter_by_rank(self, *ranks):
#        '''TODO'''
#        
#        return type(self)(f for f in self if f.match_by_rank(*ranks))
#
#    
#    def filter_by_ncvar(self, *rank):
#        '''Select field constructs by netCDF variable name.
#    
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match_by_ncvar` method of the field constucts. For
#    example, to select all field constructs which do *not* have a
#    netCDF name of 'tas':
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match_by_ncvar('tas'))
#    
#    .. versionadded:: 3.0.0
#    
#    .. seealso:: `select`, `filter_by_identity`,
#                 `filter_by_construct`, `filter_by_naxes`,
#                 `filter_by_rank`, `filter_by_units`
#    
#        ncvars: optional
#            Select field constructs. May be one or more:
#    
#              * The netCDF name of a field construct.
#    
#            A field construct is selected if it matches any of the
#            given names.
#    
#            A netCDF variable name is specified by a string (e.g.
#            ``'tas'``, etc.); a `Query` object
#            (e.g. ``cf.eq('tas')``); or a compiled regular expression
#            (e.g. ``re.compile('^air_')``) that selects the field
#            constructs whose netCDF variable names match via
#            `re.search`.
#    
#            If no netCDF variable names are provided then all field
#            are selected.
#    
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    TODO
#
#        '''     
#        return type(self)(f for f in self if f.match_by_ncvar(*ncvars))
#
#    
#    def filter_by_property(self, *mode, **properties):
#        '''Select field constructs by property.
#
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match_by_property` method of the field constucts. For
#    example, to select all field constructs which do *not* have a
#    long_name property of 'Air Pressure':
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match_by_property(long_name='Air Pressure))
#    
#    .. versionadded:: 3.0.0
#    
#    .. seealso:: `select`, `filter_by_identity`,
#                 `filter_by_construct`, `filter_by_naxes`,
#                 `filter_by_rank`, `filter_by_units`
#    
#        mode: optional
#            Define the behaviour when multiple properties are
#            provided.
#    
#            By default (or if the *mode* parameter is ``'and'``) a
#            field construct is selected if it matches all of the given
#            properties, but if the *mode* parameter is ``'or'`` then a
#            field construct will be selected when at least one of its
#            properties matches.
#    
#        properties: optional
#            Select field constructs. May be one or more of:
#    
#              * The property of a field construct.
#    
#            By default a field construct is selected if it matches all
#            of the given properties, but it may alternatively be
#            selected when at least one of its properties matches (see
#            the *mode* positional parameter).
#    
#            A property value is given by a keyword parameter of the
#            property name. The value may be a scalar or vector
#            (e.g. ``'air_temperature'``, ``4``, ``['foo', 'bar']``);
#            or a compiled regular expression
#            (e.g. ``re.compile('^ocean')``), for which all constructs
#            whose methods match (via `re.search`) are selected.
#            
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    TODO
#
#        '''
#        return type(self)(f for f in self if f.match_by_property(*mode, **properties))
#
#    
#    def filter_by_units(self, *units, exact=True):
#        '''Select field constructs by units.
#
#    To find the inverse of the selection, use a list comprehension
#    with `~Field.match_by_units` method of the field constucts. For
#    example, to select all field constructs whose units are *not*
#    ``'km'``:
#            
#       >>> gl = cf.FieldList(f for f in fl if not f.match_by_units('km'))
#    
#    .. versionadded:: 3.0.0
#    
#    .. seealso:: `select`, `filter_by_identity`,
#                 `filter_by_construct`, `filter_by_naxes`,
#                 `filter_by_rank`, `filter_by_property`
#    
#        units: optional
#            Select field constructs. By default all field constructs
#            are selected. May be one or more of:
#    
#              * The units of a field construct.
#    
#            Units are specified by a string or compiled regular
#            expression (e.g. 'km', 'm s-1', ``re.compile('^kilo')``,
#            etc.) or a `Units` object (e.g. ``Units('km')``,
#            ``Units('m s-1')``, etc.).
#            
#        exact: `bool`, optional
#            If `False` then select field constructs whose units are
#            equivalent to any of those given by *units*. For example,
#            metres and are equivelent to kilometres. By default, field
#            constructs whose units are exactly one of those given by
#            *units* are selected. Note that the format of the units is
#            not important, i.e. 'm' is exactly the same as 'metres'
#            for this purpose.
#    
#    :Returns:
#    
#        `FieldList`
#            The matching field constructs.
#    
#    **Examples:**
#    
#    >>> gl = fl.filter_by_units('metres')
#    >>> gl = fl.filter_by_units('m')
#    >>> gl = fl.filter_by_units('m', 'kilogram')
#    >>> gl = fl.filter_by_units(Units('m'))
#    >>> gl = fl.filter_by_units('km', exact=False)
#    >>> gl = fl.filter_by_units(Units('km'), exact=False)
#    >>> gl = fl.filter_by_units(re.compile('^met'))
#    >>> gl = fl.filter_by_units(Units('km'))
#    >>> gl = fl.filter_by_units(Units('kg m-2'))
#
#        '''
#        return type(self)(f for f in self
#                          if f.match_by_units(*units, exact=exact))
#
#    
##    def unordered_equals(self, other, rtol=None, atol=None,
##                         verbose=False, ignore_data_type=False,
##                         ignore_fill_value=False,
##                         ignore_properties=(),
##                         ignore_compression=False, ignore_type=False):
##        '''TODO
##
##    Two real numbers ``x`` and ``y`` are considered equal if
##    ``|x-y|<=atol+rtol|y|``, where ``atol`` (the tolerance on absolute
##    differences) and ``rtol`` (the tolerance on relative differences)
##    are positive, typically very small numbers. See the *atol* and
##    *rtol* parameters.
##    
##    :Parameters:
##    
##        atol: `float`, optional
##            The tolerance on absolute differences between real
##            numbers. The default value is set by the `ATOL` function.
##    
##        rtol: `float`, optional
##            The tolerance on relative differences between real
##            numbers. The default value is set by the `RTOL` function.
##
##        '''
##        kwargs = locals()
##        del kwargs['self']
##        kwargs['_set'] = True
##        
##        return self.equals(**kwargs)
#
#    
#
#    # ----------------------------------------------------------------
#    # Deprecated attributes and methods
#    # ----------------------------------------------------------------
#    def _parameters(self, d):
#        '''Deprecated at version 3.0.0.
#
#        '''
#        _DEPRECATION_ERROR_METHOD(self, '_parameters') # pragma: no cover
#
#
#    def _deprecated_method(self, name):
#        '''Deprecated at version 3.0.0.
#
#        '''
#        _DEPRECATION_ERROR_METHOD(self, '_deprecated_method') # pragma: no cover
#
#
#    def set_equals(self, other, rtol=None, atol=None,
#                   ignore_data_type=False, ignore_fill_value=False,
#                   ignore_properties=(), ignore_compression=False,
#                   ignore_type=False, traceback=False):
#        '''Deprecated at version 3.0.0. Use method 'equals' instead.
#        
#        '''
#        _DEPRECATION_ERROR_METHOD(self, 'set_equals',
#                                  "Use method 'equals' instead.") # pragma: no cover
#
#
#    def select_field(self, *args, **kwargs):
#        '''Deprecated at version 3.0.0. Use 'fl.filter_by_*' methods instead.
#
#        '''
#        _DEPRECATION_ERROR_METHOD(self, 'select_field',
#                                  "Use 'fl.filter_by_*' methods instead.") # pragma: no cover
#
#
#    def select1(self, *args, **kwargs):
#        '''Deprecated at version 3.0.0. Use 'fl.filter_by_*' methods instead.
#
#        '''
#        _DEPRECATION_ERROR_METHOD(self, 'select1', 
#                                  "Use 'fl.filter_by_*' methods instead.") # pragma: no cover
#
#
##--- End: class