# RL4TurtleBot3Navigation
> Use deep RL algorithms (SAC, DQN) to learn how turtlebot3 navigates in obstacle environments.

SAC performance continuous action in no obstacle environment:

![sac](https://media.giphy.com/media/fNDva8nOgmIjsdZiEw/giphy.gif)

DQN performance discrete action in static obstacle environment:

![dqn](https://media.giphy.com/media/G4zpOd4PjVqCfPSyN8/giphy.gif)

## Table of Contents
* [Overview](#overview)
* [Requirements](#requirements)
* [Training the Model](#training-the-model)

## Overview
This repository is for my internship project which contains pytorch implementation (used stable baselines 3) to train a reinforcement learning navigation model. The robot is trained in Gazebo simulator. 

## Requirements
1. Ubuntu 20.04 LTS.
2. Python 3.
3. ROS Neotic.
4. Gazebo simulator.
5. Some ROS packages: turtlebot3, openai_ros,...

## Training the Model
First run the stage simulator: 
```
roslaunch turtlebot3_gazebo turtlebot3_stage_2.launch 
```
In a separate terminal, run the training code: 
```
roslaunch my_turtlebot3_openai_example my_sb3_dqn_nav.launch
```
