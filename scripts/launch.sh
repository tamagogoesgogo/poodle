#!/usr/bin/env bash

# Prints help
usage () {
    docstring=$(cat <<-EOF
poodle [OPTION] ... <DATABASE>

Connection options:
    -l               connects to an already running MongoDB daemon on local
                     system or starts one manually
    -s <ADDRESS>     connects to a server hosted at <ADDRESS> running a MongoDB
                     daemon
Authorization options:
    -u <USERNAME>    username for authorization; usually only needed when
                     connecting to server
    -p <PASSWORD>    password for authorization; only needed when username
                     option is provided; user will be asked for password input
                     by prompt if this option is not provided
Miscellaneous options:
    -h               show this help
EOF
)
    echo "$docstring"
}

# Loading animation
loading () {
    local -a dots=( '.  ' '.. ' '...' )
    local i=-1

    while kill -0 "$1" 2>/dev/null; do
	i=$(( (i+1) % 3 ))
	printf "\r$2${dots[i]}"
	sleep .4
    done
    printf "\r$2...\nDone.\n\n"
}

# Checks for correct database
db_check () {
    local message1='Error: No database specified!\n'
    local message2='Error: Database name contains non-alphanumeric characters!\n'
    # Ensure database is not a command option
    if [[ "${1:0:1}" == '-' ]]; then
	echo -e "$message1"
	exit 1
    fi
    # Ensure database has only alphanumeric characters
    for (( i=0; i<"${#1}"; i++ )); do
        if ! [[ "${1:$i:1}" == [[:alnum:]] ]]; then
	    echo -e "$message2"
            exit 1
        fi
    done

    return 0
}

# Install system-wide dependencies based on OS
install_system_dependencies () {
    local -a already_installed

    # Ubuntu/Debian/Linux Mint
    local -a debian_packages=(
	'python3-pip' 'python3-venv' 'libxcb-cursor0'
    )
    # Install missing system packages
    cat /etc/os-release | grep -Eq '^ID=([Dd]ebian|[Uu]buntu|[Ll]inux\s?[Mm]int)' &&
	{ for i in "${debian_packages[@]}"; do
	      apt list --installed 2>/dev/null | grep -Eq "^$i[\s/]" &&
		  already_installed+=( "$i" )
	  done;
	  for i in "${already_installed[@]}"; do
	      debian_packages=( "${debian_packages[@]/$i}" )
	  done; } &&
	[[ -n "$debian_packages" ]] &&
	yes | sudo apt -qqq install "${debian_packages[@]}"

    # Manjaro/Arch — no system packages required beyond base python
    if cat /etc/os-release | grep -Eq '^ID=([Aa]rch|[Mm]anjaro)'; then
	pacman -Q python-pip &>/dev/null ||
	    yes | sudo pacman -S --needed python-pip
    fi

    # Fedora — no system packages required beyond base python
    if cat /etc/os-release | grep -Eq '^ID=fedora'; then
	rpm -q python3-pip &>/dev/null ||
	    sudo dnf install -yq python3-pip
    fi
}

# Bring Poodle up to date from GitHub before it starts. Only a copy installed
# with `git clone -b stable` updates itself: on any other branch, such as the
# main branch Poodle is developed on, this does nothing. It never overwrites
# anything: no network, local changes to Poodle's files, or a history that has
# gone its own way all mean the installed version simply starts as it is.
update_poodle () {
    [[ -n "$POODLE_JUST_UPDATED" ]] && return 0
    [[ -d .git ]] || return 0
    command -v git &>/dev/null || return 0
    [[ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" == 'stable' ]] || return 0

    echo 'Checking for a new Poodle version...'
    if ! timeout 20 git fetch --quiet origin stable 2>/dev/null; then
	echo -e 'GitHub not reachable; starting the installed version.\n'
	return 0
    fi
    # Nothing newer: the same version, or this copy is already ahead of it
    if git merge-base --is-ancestor FETCH_HEAD HEAD; then
	echo -e 'Poodle is up to date.\n'
	return 0
    fi

    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
	echo 'A new Poodle version is available, but Poodle'"'"'s own files were changed'
	echo -e 'on this computer, so it was not installed. Please ask for help.\n'
	return 0
    fi
    if ! git merge --ff-only --quiet FETCH_HEAD 2>/dev/null; then
	echo -e 'A new Poodle version could not be installed. Please ask for help.\n'
	return 0
    fi
    echo -e "Poodle updated to the version of $(git log -1 --format=%cd --date=short).\n"

    # This script may itself have changed: start the new one instead
    export POODLE_JUST_UPDATED=1
    exec bash scripts/launch.sh "$@"
}

connect_local () {
    # If no MongoDB daemon is running in background,
    # initiate one manually
    if ! ps -A | grep -q 'mongod'; then
	kill_daemon=1
	# Create directory if necessary
	if [[ "$connection_type" == 'local' ]]; then
	    if ! ls | grep -q '^mongo$'; then
		mkdir mongo
	    fi
	fi
	# Determine correct terminal emulator for async command
	term=$(ps -o comm= -p "$(($(ps -o ppid= -p "$(($(ps -o sid= -p "$$")))")))")
	case "$term" in
	    xfce4-terminal)
		xfce4-terminal -e "mongod --dbpath ./mongo --logappend"
		;;
	    gnome-terminal|gnome-terminal-)
		gnome-terminal -- sh -c "mongod --dbpath ./mongo --logappend; bash"
		;;
	    urxvt|urxvtd)
		urxvtc -e mongod --dbpath ./mongo --logappend
		;;
	    mate-terminal)
		mate-terminal --window --command="mongod --dbpath ./mongo --logappend"
		;;
	    konsole)
		konsole -e '$SHELL -c "mongod --dbpath ./mongo --logappend; $SHELL"' &
		;;
	    qterminal)
		qterminal -e "mongod --dbpath ./mongo --logappend" &
		;;
	    *)
		echo "Running on unsupported terminal: $term"
		exit 1
		;;
	esac
    fi

    connection_string='mongodb://localhost:27017'
}

connect_server () {
    # Ask for password if only username is provided
    [[ -z "$password" && -n "$username" ]] &&
	read -s -p 'Enter password:' password && echo

    connection_string="mongodb://${username}:${password}@${address}"
}

main () {
    # Parse command arguments
    while getopts "hls:u:p:" option; do
	case $option in
	    h)
		usage
		exit 0
		;;
	    l)
		[[ -n "$connection_type" ]] && usage && exit 1 ||
			connection_type='local'
		;;
	    s)
		[[ -n "$connection_type" ]] && usage && exit 1 ||
			connection_type='server'
		address="$OPTARG"
		;;
	    u)
		username="$OPTARG"
		;;
	    p)
		password="$OPTARG"
		;;
	    \?)
		exit 1
		;;
	esac
    done

    # Set base directory
    cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
    cd ".."

    update_poodle "$@"
    # Create databases directory if necessary
    if ! ls | grep -q '^databases$'; then
	mkdir databases
    fi

    # Set database
    db="${@: -1}"
    db_check "$db"

    # Connect to MongoDB
    if [[ -z "$connection_type" ]]; then
	echo -e 'Please specify a connection type (-l|-s)!\n'
	usage
	exit 1
    elif [[ "$connection_type" == 'local' ]]; then
	connect_local
    elif [[ "$connection_type" == 'server' ]]; then
	connect_server
    fi

    # Install system-wide dependencies
    install_system_dependencies &
    pid=$!
    loading "$pid" 'Checking/installing system-wide dependencies'

    # Set up virtual environment
    [[ -n "$VIRTUAL_ENV" ]] ||
	{ ls | grep -q 'venv' &&
	      echo -e 'Entering virtual environment...' &&
	      source venv/bin/activate &&
	      echo -e 'Done.\n'; } ||
	{ echo -e 'Entering virtual environment...' &&
	      python3 -m venv venv &&
	      source venv/bin/activate &&
	      echo -e 'Done.\n'; }

    # Install python packages (shown on first run; fast on subsequent runs)
    echo 'Checking/installing python packages...'
    pip3 install --no-python-version-warning -r requirements.txt
    echo 'Done.'
    echo

    # Start Poodle
    python3 -i poodle/launch.py "$username" "$password" "$connection_string" "$db"
    # Delete info stored in variables
    unset address
    unset username
    unset password
    unset connection_string

    # Kill daemon on exit if started by Poodle
    pid=$!
    wait $pid
    [[ -n "$kill_daemon" ]] &&
	pid=$(ps a | awk '/mongod/ {print $1}' | head -n 1) &&
	kill $pid
}

main "$@"
