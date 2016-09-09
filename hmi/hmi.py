# (c) 2015,2016 - Jaguar Land Rover.
#
# Mozilla Public License 2.0
#
# Python-based hmi PoC for Software Loading Manager
#

import gtk
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import time
import threading
import code, signal
import traceback
import swm
from termios import tcflush, TCIOFLUSH
import settings
import sys
import os
import getopt
import daemon


class DisplayProgress(threading.Thread):
    
    def __init__(self, *arg):
        super(DisplayProgress, self).__init__(*arg)
        self.in_progress = True
        self.update_description = None
        self.update_start_time = None
        self.update_stop_time = None
        self.operation_hmi_message = None
        self.operation_start_time = None
        self.operation_stop_time = None

    def set_manifest(self, description, start_time, stop_time):
        self.update_description = description
        self.update_start_time = start_time
        self.update_stop_time = stop_time


    def set_operation(self, hmi_message, start_time, stop_time):
        self.operation_hmi_message = hmi_message
        self.operation_start_time = start_time
        self.operation_stop_time = stop_time


    def exit_thread(self):
        self.in_progress = False
        self.join()

    def run(self):
        while self.in_progress:
            if not self.update_description:
                time.sleep(0.5)
                continue

            time.sleep(0.1)

            
            ct = time.time()
            if self.update_stop_time >= ct:
                completion = (self.update_stop_time - ct) / (self.update_stop_time - self.update_start_time)
            else:
                completion = 0.0

            print "\033[HUpdate:    {}\033[K".format(self.update_description)

            print "{}{}\033[K".format("+"*int(60.0 - completion*60), "-"*int(completion*60))


            # If no operation is in progress, clear sreen
            if not self.operation_start_time:
                continue
            
            if self.update_stop_time >= ct:
                completion = (self.operation_stop_time - ct) / (self.operation_stop_time - self.operation_start_time)
            else:
                completion = 0.0

            print "\nOperation: {}\033[K".format(self.operation_hmi_message)
            print "{}{}".format("+"*int(60.0 - completion*60), "-"*int(completion*60))
            print "\033[J"
    
#
# Human Machine Interface Service
#
class HMIService(dbus.service.Object):
    def __init__(self):
        bus_name = dbus.service.BusName('org.genivi.Hmi', 
                                        bus=dbus.SessionBus())

        dbus.service.Object.__init__(self, bus_name, '/org/genivi/Hmi')
        self.progress_thread = DisplayProgress()
        self.progress_thread.start()

        
    @dbus.service.method('org.genivi.Hmi', 
                         async_callbacks=('send_reply', 'send_error'))
    def updateNotification(self, 
                            update_id, 
                            description,
                            send_reply,
                            send_error): 

        try:
            print "HMI:  updateNotification()"
            print "  ID:            {}".format(update_id)
            print "  description:   {}".format(description)
            print "---"

            #
            # Send back an async reply to the invoking SoftwareLoadingManager
            # so that we can continue with user interaction without
            # risking a DBUS timeout
            #
            send_reply(True)

            print
            print
            print "DIALOG:"
            print "DIALOG: UPDATE AVAILABLE"
            print "DIALOG:   update_id:   {}".format(update_id)
            print "DIALOG:   Description: {}".format(description)
            print "DIALOG:"
            print "DIALOG: Process? (yes/no)"

            # If we use input or raw_input, the whole dbus loop hangs after
            # this method returns, for some reason.
            tcflush(sys.stdin, TCIOFLUSH)
            resp = sys.stdin.read(1)
            tcflush(sys.stdin, TCIOFLUSH)
            
            # resp = raw_input("DIALOG: Process? (yes/no): ")
            print 

            if len(resp) == 0 or (resp[0] != 'y' and resp[0] != 'Y'):
                approved = False
            else:
                approved = True

            #
            # Call SoftwareLoadingManager.package_confirmation() 
            # to inform it of user approval / decline.
            #
            swm.dbus_method('org.genivi.SoftwareLoadingManager','updateConfirmation', update_id, approved)

        except Exception as e:
            print "Exception: {}".format(e)
            traceback.print_exc()

        return None
        

    @dbus.service.method('org.genivi.Hmi', 
                         async_callbacks=('send_reply', 'send_error'))
    def manifestStarted(self,
                         update_id, 
                         total_time_estimate,
                         description,
                         send_reply,
                         send_error):
        try:
            print "Manifest started"
            send_reply(True)
            print "\033[H\033[J"
            ct = time.time()
            self.progress_thread.set_manifest(description,
                                              ct,
                                              ct + float(total_time_estimate) / 1000.0)
            
        except Exception as e:
            print "Exception: {}".format(e)
            traceback.print_exc()

        return None
    
    @dbus.service.method('org.genivi.Hmi', 
                         async_callbacks=('send_reply', 'send_error'))
    def operationStarted(self,
                          operation_id, 
                          time_estimate,
                          description,
                          send_reply,
                          send_error):

        try:
            print "Op started"
            send_reply(True)
            ct = time.time()
            self.progress_thread.set_operation(description, ct, ct + float(time_estimate) / 1000.0)
        except Exception as e:
            print "Exception: {}".format(e)
            traceback.print_exc()
        return None
    
    @dbus.service.method('org.genivi.Hmi', 
                         async_callbacks=('send_reply', 'send_error'))
    def updateReport(self,
                      update_id, 
                      results,
                      send_reply,
                      send_error):
        try: 
            send_reply(True)
            self.progress_thread.exit_thread()
            print "Update report"
            print "  ID:          {}".format(update_id)
            print "  results:"
            for result in results:
                print "    operation_id: {}".format(result['id'])
                print "    code:         {}".format(result['result_code'])
                print "    text:         {}".format(result['result_text'])
                print "  ---"
            print "---"
        except Exception as e:
            print "Exception: {}".format(e)
            traceback.print_exc()
        return None

class HMIDaemon(daemon.Daemon):
    """
    """
    
    def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        super(HMIDaemon, self).__init__(pidfile, stdin, stdout, stderr)

    def run(self):
        gtk.gdk.threads_init()
        DBusGMainLoop(set_as_default=True)
        hmi = HMIService()
        while True:
            gtk.main_iteration()


def usage():
    print "Usage:", sys.argv[0], "foreground|start|stop|restart"
    print
    print "  foreground     Start in foreground"
    print "  start          Start in background"
    print "  stop           Stop daemon running in background"
    print "  restart        Restart daemon running in background"
    print
    print "Example:", sys.argv[0],"foreground"
    sys.exit(1)


if __name__ == "__main__":
    print "HMI Simulator - Initializing"
    pid_file = settings.PID_FILE_DIR + os.path.splitext(os.path.basename(__file__))[0] + '.pid'

    try:  
        opts, args = getopt.getopt(sys.argv[1:], "")
    except getopt.GetoptError:
        print "HMI Simulator - Could not parse arguments."
        usage()
            
            
    for a in args:
        if a in ('foreground', 'fg'):
            print "HMI Simulator - Running"
            print "Please enter package installation approval when prompted"
            hmi_daemon = HMIDaemon(pid_file, stdin='/dev/stdin', stdout='/dev/stdout', stderr='/dev/stderr')
            hmi_daemon.run()
        elif a in ('start', 'st'):
            print "HMI Simulator - Starting"
            hmi_daemon = HMIDaemon(pid_file, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null')
            hmi_daemon.start()
        elif a in ('stop', 'sp'):
            print "HMI Simulator - Stopping"
            hmi_daemon = HMIDaemon(pid_file, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null')
            hmi_daemon.stop()
        elif a in ('restart', 're'):
            print "HMI Simulator - Restarting"
            hmi_daemon = HMIDaemon(pid_file, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null')
            hmi_daemon.restart()
        else:
            print "Unknown command: {}".format(a)
            usage()
            sys.exit(1)
