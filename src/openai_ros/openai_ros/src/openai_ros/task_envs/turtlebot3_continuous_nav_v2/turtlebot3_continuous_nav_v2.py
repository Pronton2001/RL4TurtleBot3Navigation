from turtle import done

import rospy
import numpy
from gym import spaces
from openai_ros.robot_envs import turtlebot3_env
from openai_ros.task_envs.task_commons import LoadYamlFileParamsTest
from openai_ros.openai_ros_common import ROSLauncher
from tf.transformations import euler_from_quaternion, quaternion_from_euler
import os
from math import pi, fabs, sqrt,atan2, cos, sin, modf
from openai_ros.respawnGoal import Respawn

# Waffle Pi footprint
footprint = [[-0.205, -0.155], [-0.205, 0.155], [0.077, 0.155], [0.077, -0.155]]
right_bottom_corner = footprint[0] # [x,y]
left_bottom_corner = footprint[1]
left_top_corner = footprint[2]
right_top_corner = footprint[3]
GOAL_DECAY = 1/2

class TurtleBot3ContinuousNavEnvV2(turtlebot3_env.TurtleBot3Env):
    def __init__(self):
        """
        This Task Env is designed for having the TurtleBot3 in the turtlebot3 world
        closed room with columns.
        It will learn how to move around without crashing.
        """
        # This is the path where the simulation files, the Task and the Robot gits will be downloaded if not there
        ros_ws_abspath = rospy.get_param("/turtlebot3/ros_ws_abspath", None)
        assert ros_ws_abspath is not None, "You forgot to set ros_ws_abspath in your yaml file of your main RL script. Set ros_ws_abspath: \'YOUR/SIM_WS/PATH\'"
        assert os.path.exists(ros_ws_abspath), "The Simulation ROS Workspace path " + ros_ws_abspath + \
                                               " DOESNT exist, execute: mkdir -p " + ros_ws_abspath + \
                                               "/src;cd " + ros_ws_abspath + ";catkin_make"

        ROSLauncher(rospackage_name="turtlebot3_gazebo",
                    launch_file_name="start_world.launch",
                    ros_ws_abspath=ros_ws_abspath)

        # Load Params from the desired Yaml file
        LoadYamlFileParamsTest(rospackage_name="openai_ros",
                               rel_path_from_package_to_file="src/openai_ros/task_envs/turtlebot3_nav/config",
                               yaml_file_name="turtlebot3_nav.yaml")


        # Here we will add any init functions prior to starting the MyRobotEnv
        super(TurtleBot3ContinuousNavEnvV2, self).__init__(ros_ws_abspath)

        # Only variable needed to be set here
        # number_actions = rospy.get_param('/turtlebot3/n_actions')

        # number_actions = 5
        # self.action_space = spaces.Discrete(number_actions)
        low_action = numpy.asarray([0., -pi/2])
        high_action = numpy.asarray([1., pi/2])
        self.action_space = spaces.Box(low_action, high_action) # vel: 0->1, ang_vel: -pi/2 -> pi/2

        # We set the reward range, which is not compulsory but here we do it.
        self.reward_range = (-numpy.inf, numpy.inf)


        number_observations = rospy.get_param('/turtlebot3/n_observations')
        """
        We set the Observation space for the 6 observations
        cube_observations = [
            round(current_disk_roll_vel, 0),
            round(y_distance, 1),
            round(roll, 1),
            round(pitch, 1),
            round(y_linear_speed,1),
            round(yaw, 1),
        ]
        """
        # Actions and Observations
        self.linear_forward_speed = rospy.get_param('/turtlebot3/linear_forward_speed')
        self.linear_turn_speed = rospy.get_param('/turtlebot3/linear_turn_speed')
        self.angular_speed = rospy.get_param('/turtlebot3/angular_speed')
        self.init_linear_forward_speed = rospy.get_param('/turtlebot3/init_linear_forward_speed')
        self.init_linear_turn_speed = rospy.get_param('/turtlebot3/init_linear_turn_speed')

        self.new_ranges = rospy.get_param('/turtlebot3/new_ranges')
        self.new_ranges = 24
        self.min_range = rospy.get_param('/turtlebot3/min_range')
        self.max_laser_value = rospy.get_param('/turtlebot3/max_laser_value')
        self.max_laser_value = 3.5
        self.min_laser_value = rospy.get_param('/turtlebot3/min_laser_value')
        self.max_linear_aceleration = rospy.get_param('/turtlebot3/max_linear_aceleration')

        # We create two arrays based on the binary values that will be assigned
        # In the discretization method.
        # laser_scan = self.get_laser_scan()
        # num_laser_readings = int(len(laser_scan.ranges)/self.new_ranges)
        num_laser_readings = self.new_ranges

        low_scan= numpy.full((num_laser_readings * 2 ), self.min_laser_value)
        high_scan= numpy.full((num_laser_readings * 2), self.max_laser_value)
        low_pos = numpy.array([0., -pi, 0, -pi/2,  0, -pi/2])
        high_pos = numpy.array([8., pi, 1., pi/2, 1., pi/2])
        high =  numpy.concatenate([high_scan, high_pos], axis = 0)
        low =  numpy.concatenate([low_scan, low_pos], axis = 0)

        # We only use two integers
        self.observation_space = spaces.Box(low, high) # just for sample or check contain

        rospy.logdebug("ACTION SPACES TYPE===>"+str(self.action_space))
        rospy.logdebug("OBSERVATION SPACES TYPE===>"+str(self.observation_space))

        # Rewards
        self.forwards_reward = rospy.get_param("/turtlebot3/forwards_reward")
        self.turn_reward = rospy.get_param("/turtlebot3/turn_reward")
        self.end_episode_points = rospy.get_param("/turtlebot3/end_episode_points")
        # self.goal_reaching_points = rospy.get_param("/turtlebot2/goal_reaching_points",500)

        # [Tri Huynh]
        # Goal reward
        self.goal_reaching_points = 200
        self.closeness_threshold = 0.2
        self.goal_x, self.goal_y = 0, 0
        self.initGoal = True
        self.respawn_goal = Respawn()

    def _set_init_pose(self):
        """Sets the Robot in its init pose
        """
        self.move_base( self.init_linear_forward_speed,
                        self.init_linear_turn_speed,
                        epsilon=0.05,
                        update_rate=10)
        return True

    def _init_env_variables(self):
        """
        Inits variables needed to be initialised each time we reset at the start
        of an episode.
        :return:
        """
        # Set to false Done, because its calculated asyncronously
        self._episode_done = False
        # [Tri Huynh]

        self._reached_goal = False
        self.previous_distance2goal = self._get_distance2goal()
        discretized_scan = self.discretize_scan_observation(
                                                    self.get_laser_scan(),
                                                    self.new_ranges
                                                    )
        self.l2 = self.l1 = discretized_scan
        self.current_distance2goal = self.init_distance2goal = self._get_distance2goal()
        self.current_heading = self._get_heading()
        if self.initGoal:
            self.goal_x, self.goal_y = self.respawn_goal.getPosition()
            self.initGoal = False

        self.goal_distance = self._get_distance2goal()
        
        self.prev_action = self.action = self.init_linear_forward_speed, self.init_linear_turn_speed
        self.prev_norm_acc= self.curr_norm_acc = self.get_vector_magnitude(self.get_imu().linear_acceleration)
        self.global_step = 0

    def _set_action(self, action):
        """
        This set action will Set the linear and angular speed of the turtlebot2
        based on the action number given.
        :param action: The action integer that set s what movement to do next.
        """

        rospy.logdebug("Start Set Action ==>"+str(action))
        # continuous action
        self.global_step +=1
        self.prev_action = self.action
        self.action = action
        linear_vel, ang_vel = action
    
        # We tell TurtleBot3 the linear and angular speed to set to execute
        self.move_base(linear_vel, ang_vel, epsilon=0.05, update_rate=10)

        rospy.logdebug("END Set Action ==>"+str(action))

    def _get_obs(self):
        """
        Here we define what sensor data defines our robots observations
        To know which Variables we have acces to, we need to read the
        TurtleBot3Env API DOCS
        :return:
        """
        rospy.logdebug("Start Get Observation ==>")
        # We get the laser scan data
        discretized_scan = self.discretize_scan_observation(
                                                    self.get_laser_scan(),
                                                    self.new_ranges
                                                    )
        # [Tri Huynh]: add previous scan, distace, heading
        self.l2 = self.l1
        self.l1 = discretized_scan
        self.current_distance2goal = self._get_distance2goal()
        self.current_heading = self._get_heading()

        self.curr_norm_acc = self.get_vector_magnitude(self.get_imu().linear_acceleration)

        if (self.current_distance2goal < 0.2):
            self._reached_goal = True

        # position relative to the goal x, y
        # state = self.l1 + self.l2 +  [self.normalize(self.current_distance2goal, 10), round(self._get_heading()/ pi, 2)]
        # vx, ang_vel
        vx, vyaw = self.action
        prev_vx, prev_vyaw = self.prev_action
        state = numpy.concatenate(( self.normalize(self.l1, 0, 3.5),  
                                    self.normalize(self.l2, 0, 3.5), 
                                    numpy.asarray([
                                        self.normalize(self.current_distance2goal, 0., 8.), 
                                        self.current_heading / pi , 
                                        self.normalize(vx, 0., 1.), 
                                        self.normalize(vyaw, -pi/2, pi/2),
                                        self.normalize(prev_vx, 0., 1.), 
                                        self.normalize(prev_vyaw, -pi/2, pi/2),
                                        ])
                                    ))
        # rospy.logwarn("ACTION:" + str((self.normalize(vx, 0., 1.), 
        #                                 self.normalize(vyaw, -pi/2, pi/2),
        #                                 self.normalize(prev_vx, 0., 1.), 
        #                                 self.normalize(prev_vyaw, -pi/2, pi/2))))
        # print(f"After normalize: speed: {self.normalize(vx, 0., 1.)} vyaw: {self.normalize(vyaw, -pi/2, pi/2)}")
        return state

    def _is_done(self, observations):

        # if self._episode_done:
        
        # if self._episode_done and (not self._reached_goal):
        #     rospy.logerr("TurtleBot3 is Too Close to wall==>")
        # elif self._episode_done and self._reached_goal:
        #     rospy.logwarn("Robot reached the goal")

        # Now we check if it has crashed based on the imu
        imu_data = self.get_imu()
        linear_acceleration_magnitude = self.get_vector_magnitude(imu_data.linear_acceleration)
        if linear_acceleration_magnitude > self.max_linear_aceleration:
            # rospy.logerr("TurtleBot3 Crashed==>"+str(linear_acceleration_magnitude)+">"+str(self.max_linear_aceleration))
            self._episode_done = True

        return self._episode_done

    def _compute_reward(self, observations, action, done):
        return self.setReward3(observations, done, action)
        #  [Tri Huynh] ############################3
        reward = 0
        r_towardgoal = 2
        w_oscillatory = 0.05
        w_H = 3
        if not done:
            heading = self._get_heading()
            if heading > pi/2 or heading < pi/2:
                rH = - 10 ** (-(pi - fabs(heading)))
            else:
                rH = 10 ** (-fabs(heading))
            reward += w_H * rH
            print("reward heading to goal:" + str(rH))

            rG = r_towardgoal*(self.previous_distance2goal - self.current_distance2goal)
            reward += rG
            print("reward to goal:" + str(rG))

            rO = w_oscillatory *-1* fabs(self.ang_vel) if action in [0,4] \
                else w_oscillatory * 1 * (pi/2-fabs(self.ang_vel))
            reward += rO
            print("reward Osci:" + str(rO))
        #############################3

            self.previous_distance2goal = self.current_distance2goal
            if self._reached_goal:
                # reward += self.goal_reaching_points
                reward += 200
                print("Goal !!! ")
                self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
                self.goal_distance = self._get_distance2goal()
                self._reached_goal = False


        if done:
            # if not self._reached_goal:
                # reward += -1*self.end_episode_points
                reward += -200
                print("Collision !!!: ")
        
        # Danger of collision cost
        # reward += self.collision_danger_cost
        # rospy.logerr("Total reward: " + str(reward))

        return reward

    def setReward2(self, state, done, action):
        linear_vel, ang_vel = action
        w_vel_reward = 2
        w_vel_punish = 5

        heading = self._get_heading()
        current_distance = self.current_distance2goal

        # print('heading:' + str(heading))
        # print('ang_vel:' + str(ang_vel))
        # print('distance:' + str(current_distance))
        angle = heading + ang_vel/2 + pi / 2 # 0->4
        tr = 1 - 4 * fabs(0.5 - modf(0.25 + 0.5 * angle % (2 * pi) / pi)[0])

        distance_rate = 2 ** (current_distance / self.goal_distance)
        rH = ((round(tr * 5, 2)) * distance_rate)
        # print('-> reward heading:' + str(rH))
        # if rH > 0:
        #     rV = w_vel_reward* linear_vel
        # else: 
        #     rV = w_vel_punish* linear_vel # more punish when go far from goal
        reward = 3 * rH * 10 * (self.previous_distance2goal - self.current_distance2goal)
        print(reward)

        if done:
            print("Collision!!")
            reward = -40
            # self.pub_cmd_vel.publish(Twist())

        if self._reached_goal:
            print("Goal!!")
            reward = 200
            # self.pub_cmd_vel.publish(Twist())
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
            self._reached_goal = False

        return reward

    def setReward3(self, state, done, action):
        linear_vel, ang_vel = action
        w_vel_reward = 2
        w_vel_punish = 5
        w_sharp_turn = 5
        w_continuous = 5
        w_time = 1

        heading = self._get_heading()
        current_distance = self.current_distance2goal

        # print('heading:' + str(heading))
        # print('ang_vel:' + str(ang_vel))
        # print('distance:' + str(current_distance))
        angle = heading + ang_vel/2 + pi / 2 # 0->4
        tr = 1 - 4 * fabs(0.5 - modf(0.25 + 0.5 * angle % (2 * pi) / pi)[0])

        distance_rate = (current_distance / (self.goal_distance + .2))
        rH = ((round(tr * 5, 2)) * distance_rate)
        # print('-> reward heading:' + str(rH))
        if rH > 0:
            rV = w_vel_reward* linear_vel
        else: 
            rV = w_vel_punish* linear_vel # more punish when go far from goal
        # print('-> reward heading + vel:' + str(rH * rV))

        norm_ang_vel = fabs(ang_vel)
        rST = -w_sharp_turn * norm_ang_vel if norm_ang_vel > pi/4 else 0
        # print(f"norm_ang_vel: {norm_ang_vel}")
        # print(f"-> rST: {rST}")

        acc_change = fabs(self.prev_norm_acc - self.curr_norm_acc)
        rC = - w_continuous * acc_change if acc_change > .1 else 0
        # print(f"acc_change: {acc_change}")
        # print(f"-> rC: {rC}")

        reward = rH * rV + rST + rC

        self.prev_norm_acc = self.curr_norm_acc
        if done:
            print("Collision!!")
            rTime = -w_time * (200 - self.global_step) # since 200 is maximum. [TODO: get max_env_step instead of 200]
            rCollision = -200
            reward = rTime + rCollision
            # self.pub_cmd_vel.publish(Twist())

        if self._reached_goal:
            print("Goal!!")
            reward = 200
            # self.pub_cmd_vel.publish(Twist())
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
            self._reached_goal = False

        return reward


    def setReward(self, state, done, action):
        linear_vel, ang_vel = action
        w_vel_reward = 2
        w_vel_punish = 5

        heading = self._get_heading()
        current_distance = self.current_distance2goal

        # print('heading:' + str(heading))
        # print('ang_vel:' + str(ang_vel))
        # print('distance:' + str(current_distance))
        angle = heading + ang_vel/2 + pi / 2 # 0->4
        tr = 1 - 4 * fabs(0.5 - modf(0.25 + 0.5 * angle % (2 * pi) / pi)[0])

        distance_rate = 2 ** (current_distance / self.goal_distance)
        rH = ((round(tr * 5, 2)) * distance_rate)
        # print('-> reward heading:' + str(rH))
        if rH > 0:
            rV = w_vel_reward* linear_vel
        else: 
            rV = w_vel_punish* linear_vel # more punish when go far from goal
        reward = rH * rV

        if done:
            print("Collision!!")
            reward = -200
            # self.pub_cmd_vel.publish(Twist())

        if self._reached_goal:
            print("Goal!!")
            reward = 200
            # self.pub_cmd_vel.publish(Twist())
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
            self._reached_goal = False

        return reward

    # Internal TaskEnv Methods
    # [Tri Huynh] 
    def discretize_scan_observation(self, scan, new_ranges):
        """
        Discards all the laser readings that are not multiple in index of new_ranges
        value.
        """
        scan_range = []
        kernel_size = len(scan.ranges)// new_ranges
        for i in range(0, len(scan.ranges), kernel_size):
            if scan.ranges[i] == float('Inf'):
                scan_range.append(3.5)
            elif numpy.isnan(scan.ranges[i]):
                scan_range.append(0)
            else:
                scan_range.append(scan.ranges[i])
            if self.min_range > scan.ranges[i]:
                self._episode_done = True
        return scan_range

    def get_vector_magnitude(self, vector):
        """
        It calculated the magnitude of the Vector3 given.
        This is usefull for reading imu accelerations and knowing if there has been
        a crash
        :return:
        """
        contact_force_np = numpy.array((vector.x, vector.y, vector.z))
        force_magnitude = numpy.linalg.norm(contact_force_np) # F = ma with m = 1  => a = F

        return force_magnitude

    def _get_distance2goal(self):
        """ Gets the distance to the goal
        """
        odom = self.get_odom()
        odom_x, odom_y = odom.pose.pose.position.x, odom.pose.pose.position.y
        return sqrt((self.goal_x - odom_x)**2 + (self.goal_y - odom_y)**2) # NOTE: Distnce Alway less than 10m 

    def _get_heading(self):
        # goal_x, goal_y = self._get_goal_location()
        odom = self.get_odom()
        odom_x, odom_y = odom.pose.pose.position.x, odom.pose.pose.position.y
        # robot_to_goal_x = int((goal_x - odom_x) * 2.4999) # assume maximum is 4, scaled up to 9
        # robot_to_goal_y = int((goal_y - odom_y) * 2.4999)
        orientation = odom.pose.pose.orientation
        orientation_list = [orientation.x, orientation.y, orientation.z, orientation.w]
        _, _, yaw = euler_from_quaternion(orientation_list)
        goal_angle = atan2(self.goal_y - odom_y, self.goal_x - odom_x)
        heading = goal_angle - yaw
        if heading > pi:
            heading -= 2 * pi
        elif heading < -pi:
            heading += 2 * pi
        # if heading > 3 * pi / 4 or heading < 3* pi /4:
        #     self._episode_done = True
        return heading 


    def obsBack(self, x, y):
        return x <= 0 and x >= -self.closeness_threshold and y <= left_bottom_corner[1] and y >= right_bottom_corner[1]

    def obsFront(self, x, y):
        return x >= 0 and x <= self.closeness_threshold and y <= left_bottom_corner[1] and y >= right_bottom_corner[1]

    def obsRight(self, x, y):
        return x <= right_top_corner[0] and x >= right_bottom_corner[0] and y >= -self.closeness_threshold and y <= 0
        
    def obsLeft(self, x, y):
        return x <= right_top_corner[0] and x >= right_bottom_corner[0]  and y >= 0 and y <= self.closeness_threshold

    def normalize(self, x, low, high):
        return 2 * (numpy.asarray(x) - low) / (high - low) - 1