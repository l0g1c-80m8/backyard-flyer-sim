import argparse
import time
from enum import Enum

import numpy as np

from udacidrone import Drone
from udacidrone.connection import MavlinkConnection, WebSocketConnection  # noqa: F401
from udacidrone.messaging import MsgID


class States(Enum):
    MANUAL = 0
    ARMING = 1
    TAKEOFF = 2
    WAYPOINT = 3
    LANDING = 4
    DISARMING = 5


class BackyardFlyer(Drone):

    def __init__(self, connection):
        super().__init__(connection)
        self.target_position = np.array([0.0, 0.0, 0.0])
        self.all_waypoints = []
        self.in_mission = True
        self.check_state = {}

        # initial state
        self.flight_state = States.MANUAL

        # Register all your callbacks here
        self.register_callback(MsgID.LOCAL_POSITION, self.local_position_callback)
        self.register_callback(MsgID.LOCAL_VELOCITY, self.velocity_callback)
        self.register_callback(MsgID.STATE, self.state_callback)

    def local_position_callback(self):
        """
        This triggers when `MsgID.LOCAL_POSITION` is received and self.local_position contains new data
        """
        if self.flight_state == States.TAKEOFF:
            # during takeoff, reach target altitude first
            # coordinate conversion
            if -1 * self.local_position[2] > 0.95 * self.target_position[2]:
                # if altitude is within 95% of target altitude, set waypoints and begin transition
                self.all_waypoints = self.calculate_box()
                self.waypoint_transition()
        elif self.flight_state == States.WAYPOINT:
            """
            during mission, check if drone is within 95% of current waypoint,
            if so, transition to next waypoint
            """
            # np.linalg.norm(): https://numpy.org/doc/stable/reference/generated/numpy.linalg.norm.html
            # matrix norm: https://en.wikipedia.org/wiki/Matrix_norm - magnitude of the vector
            # norm: https://en.wikipedia.org/wiki/Norm_(mathematics) - euclidean distance
            if np.linalg.norm(self.target_position[0:2] - self.local_position[0:2]) < 1.0:
                # if there is a next waypoint, set it as target waypoint, else prepare for landing
                if len(self.all_waypoints) > 0:
                    self.waypoint_transition()
                elif np.linalg.norm(self.local_velocity[0:2]) < 0.1:
                    # wait for the drone to become stationary before commencing landing
                    # else, landing takes place abruptly
                    self.landing_transition()

    def velocity_callback(self):
        """
        This triggers when `MsgID.LOCAL_VELOCITY` is received and self.local_velocity contains new data
        """
        if self.flight_state == States.LANDING:
            # when landing has begun, and drone is near starting position, disarm
            if self.global_position[2] - self.global_home[2] < 0.1:
                # when drone is near the ground, disarm
                if abs(self.local_position[2]) < 0.05:
                    self.disarming_transition()

    def state_callback(self):
        """
        This triggers when `MsgID.STATE` is received and self.armed and self.guided contain new data
        """
        if not self.in_mission:
            return

        if self.flight_state == States.MANUAL:
            self.arming_transition()
        elif self.flight_state == States.ARMING:
            self.takeoff_transition()
        elif self.flight_state == States.DISARMING:
            self.manual_transition()

    def flight_plan_coordinates(self):
        """
        1. Return relative coordinates in the format:
            [x_start, x_end, y_start, y_end, altitude]
        """
        return [0.0, 20.0, 0.0, 20.0, 3.0]

    def calculate_box(self):
        """
        1. Return waypoints to fly a box
        """
        [x_start, x_end, y_start, y_end, altitude] = self.flight_plan_coordinates()
        return [[x_end, y_start, altitude], [x_end, y_end, altitude], [x_start, y_end, altitude], [x_start, y_start, altitude]]

    def arming_transition(self):
        """
        1. Take control of the drone
        2. Pass an arming command
        3. Set the home location to current position
        4. Transition to the ARMING state
        """
        print("arming transition")
        self.take_control()
        self.arm()

        # set the current location to be the home position
        self.set_home_position(self.global_position[0],
                               self.global_position[1],
                               self.global_position[2])

        self.flight_state = States.ARMING

    def takeoff_transition(self):
        """
        1. Set target_position altitude to 3.0m
        2. Command a takeoff to 3.0m
        3. Transition to the TAKEOFF state
        """
        print("takeoff transition")
        target_altitude = self.flight_plan_coordinates()[4]
        # set current altitude to target_altitude
        self.target_position[2] = target_altitude
        # takeoff and assume target_altitude
        self.takeoff(target_altitude)
        # Set state to takeoff
        self.flight_state = States.TAKEOFF

    def waypoint_transition(self):
        """
        1. Command the next waypoint position
        2. Transition to WAYPOINT state
        """
        # update target_position to next waypoint and remove it from waypoints to visit list
        self.target_position = self.all_waypoints.pop(0)
        print("waypoint transition", self.target_position)
        # set new position to the updated target_position
        self.cmd_position(self.target_position[0], self.target_position[1], self.target_position[2], 0.0)
        self.flight_state = States.WAYPOINT

    def landing_transition(self):
        """
        1. Command the drone to land
        2. Transition to the LANDING state
        """
        print("landing transition")
        self.land()
        self.flight_state = States.LANDING

    def disarming_transition(self):
        """
        1. Command the drone to disarm
        2. Transition to the DISARMING state
        """
        print("disarm transition")
        self.disarm()
        self.flight_state = States.DISARMING

    def manual_transition(self):
        """This method is provided
        
        1. Release control of the drone
        2. Stop the connection (and telemetry log)
        3. End the mission
        4. Transition to the MANUAL state
        """
        print("manual transition")

        self.release_control()
        self.stop()
        self.in_mission = False
        self.flight_state = States.MANUAL

    def start(self):
        """This method is provided
        
        1. Open a log file
        2. Start the drone connection
        3. Close the log file
        """
        print("Creating log file")
        self.start_log("Logs", "NavLog.txt")
        print("starting connection")
        self.connection.start()
        print("Closing log file")
        self.stop_log()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5760, help='Port number')
    parser.add_argument('--host', type=str, default='127.0.0.1', help="host address, i.e. '127.0.0.1'")
    args = parser.parse_args()

    conn = MavlinkConnection('tcp:{0}:{1}'.format(args.host, args.port), threaded=False, PX4=False)
    #conn = WebSocketConnection('ws://{0}:{1}'.format(args.host, args.port))
    drone = BackyardFlyer(conn)
    time.sleep(2)
    drone.start()
