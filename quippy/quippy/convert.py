# HQ XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# HQ X
# HQ X   quippy: Python interface to QUIP atomistic simulation library
# HQ X
# HQ X   Portions of this code were written by
# HQ X     Tamas K. Stenczel, James Kermode
# HQ X
# HQ X   Copyright 2019
# HQ X
# HQ X   These portions of the source code are released under the GNU General
# HQ X   Public License, version 2, http://www.gnu.org/copyleft/gpl.html
# HQ X
# HQ X   If you would like to license the source code under different terms,
# HQ X   please contact James Kermode, james.kermode@gmail.com
# HQ X
# HQ X   When using this software, please cite the following reference:
# HQ X
# HQ X   https://warwick.ac.uk/fac/sci/eng/staff/jrk
# HQ X
# HQ XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX


"""
Conversions between ase and fortran atoms objects
"""
import inspect
from copy import deepcopy as cp

import _quippy
import ase
import f90wrap.runtime
import numpy as np
import quippy

__all__ = ['ase_to_quip', 'descriptor_data_mono_to_dict', 'velocities_ase_to_quip', 'velocities_quip_to_ase', 'set_doc']

# conversion between ase and quip mass, taken from Fortran source
MASSCONVERT = 103.6426957074462


def ase_to_quip(ase_atoms: ase.Atoms, quip_atoms=None, add_arrays=None, add_info=None):
    """
    Converter to put the info from an ase atoms object into a quip atoms object.
    Copies everything to make sure there is not linking back.

    Notes on add_arrays and add_info:
        - overwriting a parameter is not possible yet
        - only float arrays can be added, integers are converted to floats by fortran, fails for strings
        - keys can only be strings, as the fortran dictionary will not accept anything else,\
        integer keys are converted to strings
        - possible types:
            None - only the basic ones
            list - all the list elements are added
            True - all of the arrays

    :param ase_atoms:
    :param quip_atoms:
    :param add_arrays: keys to take from ase.Atoms.arrays
    :param add_info:  keys to take from ase.Atoms.info
    :return:
    """

    lattice = ase_atoms.get_cell().T.copy()
    if quip_atoms is not None:
        if isinstance(quip_atoms, quippy.atoms_types_module.Atoms):
            # check if the length matches, otherwise make a new one in place of that
            if len(ase_atoms) != quip_atoms.n:
                # need to regenerate the quip atoms object
                quip_atoms = quippy.atoms_types_module.Atoms(len(ase_atoms), lattice)
            else:
                # but the cell needs to be set anyways
                quip_atoms.set_lattice(lattice, scale_positions=False)
        else:
            # raise an error for the wrong object given
            raise TypeError('quip_atoms argument is not of valid type, cannot work with it')

    else:
        # need to regenerate the quip atoms object
        quip_atoms = quippy.atoms_types_module.Atoms(len(ase_atoms), lattice)

    quip_atoms.pos[:] = ase_atoms.get_positions().T.copy()
    quip_atoms.is_periodic[:] = ase_atoms.get_pbc()
    quip_atoms.z[:] = ase_atoms.numbers
    quip_atoms.set_atoms(quip_atoms.z)  # set species and mass

    if ase_atoms.has('momenta'):
        # if ase atoms has momenta then add velocities to the quip object
        # workaround for the interfaces not behaving properly in the wrapped code, see f90wrap issue #86
        _quippy.f90wrap_atoms_add_property_real_2da(this=quip_atoms._handle, name='velo',
                                                    value=velocities_ase_to_quip(ase_atoms.get_velocities()))

    # go through all properties for issue#170
    if add_arrays is not None:
        if add_arrays is True:
            # taking all the array keys that are not handled elsewhere
            add_arrays = set(ase_atoms.arrays.keys())
            [add_arrays.discard(used_key) for used_key in ['numbers', 'positions', 'momenta']]
            add_arrays = list(add_arrays)
        elif isinstance(add_arrays, str):
            # if only one is given as a string
            add_arrays = [add_arrays]
        elif isinstance(add_arrays, list) or isinstance(add_arrays, np.ndarray):
            add_arrays = list(add_arrays)
        else:
            # fixme: decide what to do here, now it is just not adding anything
            add_arrays = []

        for property_name in add_arrays:
            try:
                value = np.array(ase_atoms.arrays[property_name])
            except KeyError:
                # fixme: give some warning here if needed
                continue

            # add the value, as 1d or 2d array
            dim = len(value.shape)
            arr_dtype_kind = value.dtype.kind

            # decide the fortran type
            if arr_dtype_kind == 'b':
                fortran_type_name = 'logical'
            elif arr_dtype_kind in ['u', 'i']:
                fortran_type_name = 'int'
            elif arr_dtype_kind == 'f':
                fortran_type_name = 'real'
            elif arr_dtype_kind in ['S', 'U']:
                fortran_type_name = 'str'
            else:
                # so it is one of:
                # c complex floating - point
                # m timedelta
                # M datetime
                # O object
                # V void
                raise TypeError('given dtype ({}) is not supported'.format(arr_dtype_kind))

            # decide dim
            if dim == 1:
                add_property_method = getattr(_quippy, 'f90wrap_atoms_add_property_{}_a'.format(fortran_type_name))
                add_property_method(this=quip_atoms._handle, name=property_name, value=value)
            elif dim == 2:
                add_property_method = getattr(_quippy, 'f90wrap_atoms_add_property_{}_2da'.format(fortran_type_name))
                add_property_method(this=quip_atoms._handle, name=property_name, value=value.T)
            else:
                raise ValueError(
                    'unsupported dimension ({}) of attribute in conversion from ase to quip atoms objects'.format(dim))

    return quip_atoms


def velocities_ase_to_quip(velocities):
    """
    Convert the ASE velocities to QUIP velocities

    :param velocities: velocities obtained from ase, with Atoms.get_velocities()
    :return:
    """

    return (velocities / np.sqrt(MASSCONVERT)).T


def velocities_quip_to_ase(velocities):
    """
    Convert the QUIP velocities to ASE velocities

    :param velocities: velocities obtained from quip, with quip_atom.velo[:]
    :return:
    """

    return (velocities * np.sqrt(MASSCONVERT)).T


def descriptor_data_mono_to_dict(desc_data_mono):
    """
    Returns a dictionary out of the descriptor_data_mono object with all info it contained.
    :param desc_data_mono:
    :return:
    """

    if not isinstance(desc_data_mono, quippy.descriptors_module.descriptor_data_mono):
        raise TypeError('Not descriptor_data_mono given')

    out_data_dict = dict()

    def take_value(key):
        """
        Take the arg if it exists
        """

        try:
            out_data_dict[key] = getattr(desc_data_mono, key)
        except AttributeError:
            pass
        except ValueError:
            pass

    # fixme: only take the ones actually needed, this is good for debugging now though
    for key in ['has_grad_data', 'ii', 'pos', 'grad_covariance_cutoff', 'covariance_cutoff', 'data', 'has_data',
                'grad_data', 'ci']:
        take_value(key)

    return out_data_dict


def get_dict_arrays(fdict):
    """Takes the arrays from a quippy dictionary. Copies.

    Probably fails if there are non-array elements in the dictionary"""

    if not isinstance(fdict, quippy.dictionary_module.Dictionary):
        raise TypeError('fdict argument is not a quippy.dictionary_module.Dictionary')

    arrays = {}
    for i in range(1, fdict.n + 1):
        key = fdict.get_key(i)
        key = key.strip().decode('ascii')
        # fixme: fails for non_array elements. Make universal: compatible with array or scalar content in dictionary
        try:  # this is an unsufficient temporary fix
            value = f90wrap.runtime.get_array(f90wrap.runtime.sizeof_fortran_t,
                                              fdict._handle, _quippy.f90wrap_dictionary__array__, key)
            arrays[key] = value.copy()
        except ValueError:
            value = fdict.get_value(key)
            try:
                # normally it is an tuple, because the error arf from fortran is converted to output
                arrays[key] = cp(value[0])
            except TypeError:
                arrays[key] = cp(value)

    return arrays


def set_doc(doc, extra):
    def wrap(method):
        method.__doc__ = update_doc_string(doc, extra)
        return method

    return wrap


def update_doc_string(doc, extra, sections=None, signature=None):
    """
    Insert `extra` in the docstring `doc`, before the first matching section

    Searches for each section heading in the list `sections` in turn.
    If sections is not given, the default is `['Parameters', 'See also']`.
    If not sections are found, extra text is appended to end of docstring.
    """

    if sections is None:
        sections = ['Parameters', 'See also']

    try:
        doc = inspect.cleandoc(doc)
        extra = inspect.cleandoc(extra)
    except AttributeError:
        pass

    extra = '\n' + extra + '\n'

    lines = doc.split('\n')

    if signature is not None:
        lines[0] = signature

    for section in sections:
        indices = [i for i, line in enumerate(lines) if line == section]
        if len(indices) == 1:
            break
    else:
        indices = [len(lines) - 1]  # insert at end

    index, = indices
    doc = '\n'.join([line.rstrip() for line in lines[:index] + extra.split('\n') + lines[index:]])
    doc = doc.replace('\n\n\n', '\n\n')

    return doc
