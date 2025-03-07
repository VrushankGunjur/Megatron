import dspy
from typing import Literal, List


planning_signature = "You're part of a system that takes in a plain english objective and executes a series of bash commands in a \
    terminal to achieve that objective. This system works in a few steps: \
 \
    1. A plan is created from the english objective outlining the steps that must be taken to achieve the objective \
    2. The plan is sent to an execution step, which turns the lowest-numbered objective that isn't marked as finished into a runnable bash command \
    3. The bash command is executed in a terminal, and the results are sent back \
    4. The system goes into replanning, where the plan is updated -- if the command that was just run successfully achieved an objective, that objective is marked as finished \
    Otherwise, the system adds some information about the error or adds more steps to the plan in any order it sees fit to achieve the objective. \
 \
 \
    You're responsible for the replanning step. You'll be given the history of the execution, and your goal is to provide two things: \
    1. If the overall objective has been achieved \
    2. An updated plan, with each finished objective being followed by [FINISHED] "

replanning_prompt = "    You're part of a system that takes in a plain english objective and executes a series of bash commands in a \
    terminal to achieve that objective. This system works in a few steps: \
 \
    1. A plan is created from the english objective outlining the steps that must be taken to achieve the objective \
    2. The plan is sent to an execution step, which turns the lowest-numbered objective that isn't marked as finished into a runnable bash command \
    3. The bash command is executed in a terminal, and the results are sent back \
    4. The system goes into replanning, where the plan is updated -- if the command that was just run successfully achieved an objective, that objective is marked as finished \
    Otherwise, the system adds some information about the error or adds more steps to the plan in any order it sees fit to achieve the objective. \
 \
 \
    You're responsible for the replanning step. You'll be given the history of the execution, and your goal is to provide two things: \
    1. If the overall objective has been achieved \
    2. An updated plan, with each finished objective being followed by [FINISHED] " 


class Replanning(dspy.Signature):
  """
    You're part of a system that takes in a plain english objective and executes a series of bash commands in a 
    terminal to achieve that objective. This system works in a few steps:

    1. A plan is created from the english objective outlining the steps that must be taken to achieve the objective
    2. The plan is sent to an execution step, which turns the lowest-numbered objective that isn't marked as finished into a runnable bash command
    3. The bash command is executed in a terminal, and the results are sent back
    4. The system goes into replanning, where the plan is updated -- if the command that was just run successfully achieved an objective, that objective is marked as finished
    Otherwise, the system adds some information about the error or adds more steps to the plan in any order it sees fit to achieve the objective.


    You're responsible for the replanning step. You'll be given the history of the execution, and your goal is to provide two things:
    1. If the overall objective has been achieved
    2. An updated plan, with each finished objective being followed by [FINISHED] 
  """

  history: List[str] = dspy.InputField(description="The history of the execution on the plan")

  done: Literal["yes", "no"] = dspy.OutputField(description="Whether the overall objective has been achieved")
  new_plan = dspy.OutputField(description="Updated plan, with finished objectives marked as finished")


class Planning(dspy.Signature):
  """
      You're part of a system that takes in a plain english objective and executes a series of bash commands in a 
    terminal to achieve that objective. This system works in a few steps:

    1. A plan is created from the english objective outlining the steps that must be taken to achieve the objective
    2. The plan is sent to an execution step, which turns the lowest-numbered objective that isn't marked as finished into a runnable bash command
    3. The bash command is executed in a terminal, and the results are sent back
    4. The system goes into replanning, where the plan is updated -- if the command that was just run successfully achieved an objective, that objective is marked as finished
    Otherwise, the system adds some information about the error or adds more steps to the plan in any order it sees fit to achieve the objective.


    You're responsible for the planning step. You'll be given the plain english
    objective, and your goal is to provide a plan that outlines the steps that
    must be taken to achieve the objective. Provide a numbered list in logical
    order for the steps that must be taken to achieve the objective.
  """

  objective = dspy.InputField(description="The plain english objective")

  plan = dspy.OutputField(description="The plan outlining the steps that must be taken to achieve the objective")