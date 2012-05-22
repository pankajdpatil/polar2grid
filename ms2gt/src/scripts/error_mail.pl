#==============================================================================
# diemail - A replacement for die.  This ends the process on error, and also 
#    sends an email message to a user.
#
# 11-Apr-1997 T.Hutchinson hutch@hummock.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
# "$Header: /usr/people/haran/navdir/src/scripts/error_mail.pl,v 1.18 2001/07/19 23:37:55 haran Exp $"
#
#    input: $message - a message to print out to stderr and email to the user
#
#    The user to send the email message to is defined in $user_mail_address.  
#    If this variable is not set when this subroutine is called, the email 
#    message will not be sent.
#

sub diemail {

    my ($message) = $_[0];
    my ($filename, $line, $subject, $time);

    ($package, $filename, $line)=caller;
    $time = localtime( time() );
    $message=$message." at $filename line $line";
# Uses entire message as subject
    $subject=$message;
    if (defined($user_mail_address)) {
	system("echo \"$message\" | Mail -s \"$subject\" $user_mail_address");
    }
    print ">>>$time $message\n";
    exit 255;
}

#==============================================================================
# warnmail - A replacement for warn.  This gives a warning message, and also 
#    sends an email message to a user.
#
# 11-Apr-1997 T.Hutchinson hutch@hummock.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
# "$Id"
#
#    input: $message - a message to print out and send to the user
#
#    The user to send the email message to is defined in $user_mail_address.  
#    If this variable is not set when this subroutine is called, the email 
#    message will not be sent.
#

sub warnmail {

    my ($message) = $_[0];
    my ($filename, $line, $subject, $time);

    ($package, $filename, $line)=caller;
    $time = localtime( time() );
    $message=$message." at $filename line $line";
# Uses entire message as subject
    $subject=$message;
    if (defined($user_mail_address)) {
	system("echo \"$message\" | Mail -s \"$subject\" $user_mail_address");
    }
    print ">>>$time $message\n";
}

#==============================================================================
# print_stderr - A replacement for print STDERR. Includes date-time stamp 
#    prints a message to STDERR with a date-time stamp
#
# 6-NOV-1997 T.Haran haran@kryos.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
# "$Id"
#
#    input: $message - a message to print out
#

sub print_stderr {

    my ($message) = $_[0];
    my ($time);

    if (defined($message)) {
	$time = localtime( time() );
	print STDERR ">>>$time $message";
    }
}

#==============================================================================
# do_or_die - use system() to execute a command line or die trying
#
# 25-May-1999 T.Haran haran@kryos.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
#    input: $command - string to be passed to system()
#
#    global: $script - when an error occurs, used to identify the program
#                      that generated the error
#

sub do_or_die {

    my ($command) = @_;

    my $s = (defined($script)) ? "$script:" : "";
    if (system("$command")) {
	$command =~ s/\"//g;
	diemail("$s FATAL:\n[$command]\nfailed");
    }
}

#==============================================================================
# get_or_die - use backquotes to execute a command line and
#                  capture its output or die trying
#
# 27-May-1999 T.Haran haran@kryos.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
#    input: $command - string to be invoked with backquotes
#           @expected_return - expected return values from command;
#                              default value = 0.
#
#    global: $script - when an error occurs, used to identify the program
#                      that generated the error
#
#    return: array of output lines from stdout generated by $command
#

sub get_or_die {

    my ($command, @expected_return) = @_;

    if (!@expected_return) {
	$expected_return[0] = 0;
    }
    my $s = (defined($script)) ? "$script:" : "";
    my @ret_array = `$command`;
    my $got_one = 0;
    my $ev;
    foreach $ev (@expected_return) {
	if ($ev * 256 == $?) {
	    $got_one = 1;
	    last;
	}
    }
    if (!$got_one) {
	foreach $ev (@expected_return) {
	    print "expected return = $ev\n";
	}
	print "actual return = $?\n";
	$command =~ s/\"//g;
	diemail("$s FATAL:\n[$command]\nfailed", );
    }
    return @ret_array;
}

#==============================================================================
# chdir_or_die - change directory or die trying
#
# 26-May-1999 T.Haran haran@kryos.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
#    input: $directory - directory to be changed to 
#
#    global: $script - when an error occurs, used to identify the program
#                      that generated the error
#

sub chdir_or_die {

    my($directory) = @_;

    my $s = (defined($script)) ? "$script:" : "";
    chdir $directory || diemail("$s FATAL:\n" .
				"[chdir $directory]\nfailed");
}

#==============================================================================
# open_or_die - open a file or die trying
#
# 13-July-1999 T.Haran haran@kryos.colorado.edu 303-492-1847
# National Snow & Ice Data Center, University of Colorado, Boulder
# Boulder, CO  80309-0449
#==============================================================================
#
#    input: $handle_string - file handle
#           $filename_string - string used in opening the file
#
#    global: $script - when an error occurs, used to identify the program
#                      that generated the error
#

sub open_or_die {

    my($handle_string, $filename_string) = @_;

    my $s = (defined($script)) ? "$script:" : "";
    open($handle_string, $filename_string) ||
	diemail("$s FATAL:\n[open($handle_string, $filename_string)]\nfailed");
}

# this makes the library work correctly when using the require command
1;
