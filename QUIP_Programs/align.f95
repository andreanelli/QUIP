program align_prog
use libatoms_module
implicit none
  type(Atoms) :: at
  type(Dictionary) :: cli_params
  real(dp) :: cutoff_factor

  real(dp) :: CoM(3), MoI(3,3), MoI_evecs(3,3), MoI_evals(3)
  real(dp) :: rot_mat(3,3)
  integer :: i, ii(1)
  real(dp), allocatable :: orig_mass(:)
  real(dp), pointer :: mass(:)
  character(len=2048) :: props

  call system_initialise()

  call initialise(cli_params)
  call param_register(cli_params, 'cutoff_factor', '1.0', cutoff_factor)
  if (.not. param_read_args(cli_params, do_check = .true.)) then
    call print("Usage: align [cutoff_factor=1.0]", ERROR)
    call system_abort("Confused by CLI parameters")
  endif
  call finalise(cli_params)

  call read_xyz(at, "stdin")
  props = prop_names_string(at)

  if (.not.(assign_pointer(at,'mass', mass))) then
    call add_property(at,'mass',ElementMass(at%Z))
    if (.not.(assign_pointer(at,'mass', mass))) &
      call system_abort("ERROR: Impossible failure to add mass property to atoms")
    mass = 1.0_dp
  else
    allocate(orig_mass(at%N))
    orig_mass = mass
    mass = 1.0_dp
  endif

  call set_cutoff_factor(at, cutoff_factor)
  call calc_connect(at)

  call coalesce_in_one_periodic_image(at)

  CoM = centre_of_mass(at)
  do i=1, at%N
    at%pos(:,i) = at%pos(:,i) - CoM(:)
  end do

  MoI = moment_of_inertia_tensor(at)
  call diagonalise(MoI, MoI_evals, MoI_evecs)

  do i=1, 3
    ii = maxloc(MoI_evals)
    rot_mat(i,:) = MoI_evecs(:,ii(1))
    MoI_evals(ii(1)) = -1.0e38_dp
  end do

  do i=1, at%N
    at%pos(:,i) = matmul(rot_mat,at%pos(:,i))
  end do

  if (allocated(orig_mass)) then
    mass = orig_mass
    deallocate(orig_mass)
  endif

  call print("props" // trim(props))
  mainlog%prefix="ALIGNED"
  call print_xyz(at, mainlog, properties=trim(props))
  mainlog%prefix=""

  call system_finalise()
end program
