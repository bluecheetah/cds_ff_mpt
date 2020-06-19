
process_technology \
    -technology_library_file qrc.tech.lib \
    -technology_name cdsqrctech \
    -technology_corner typical \
    -temperature 25

output_setup \
    -file_name {{ cell_name }}.spf \
    -net_name_space schematic \
    -temporary_directory_name temp_dir \
    -keep_temporary_files true

output_db -type dspf \
    -subtype standard \
    -include_res_model "true" \
    -device_finger_delimiter "@" \
    -delete_x true \
    -add_bulk_terminal "true" \
    -hierarchy_delimiter "/" \
    -add_explicit_vias true \
    -include_cap_model "false" \
    -include_parasitic_cap_model "comment" \
    -include_parasitic_res_model "comment" \
    -include_parasitic_res_length true \
    -include_parasitic_res_width_drawn true \
    -sub_node_char ":" \
    -disable_instances false \
    -force_subcell_pin_orders true \
    -suppress_empty_subckts true \
    -merge_feedthrough_pins true \
    -pin_order_file {{ netlist_file }} \
    -output_xy canonical_cap canonical_res mos generic diode bipolar

parasitic_reduction \
    -enable_reduction false \
    -reduction_level off \
    -reduction_control 0.5

capacitance \
    -ground_net VSS

extract \
    -selection all \
    -type rc_coupled

graybox -type "layout"

log_file \
    -file_name qrc_output.log \
    -dump_options true

extraction_setup \
    -net_name_space "schematic" \
    -analysis em \


filter_coupling_cap \
    -total_cap_threshold 0.00 \
    -coupling_cap_threshold_absolute 0.01 \
    -coupling_cap_threshold_relative 0.005

filter_cap \
    -exclude_floating_nets true \
    -exclude_self_cap true \
    -exclude_floating_nets_limit 10000

filter_res \
    -min_res 0.001 \
    -remove_dangling_res false \
    -merge_parallel_res false

# hierarchical_extract -split_feedthrough_pins true -split_feedthrough_pins_distance 0.001

input_db \
    -type pegasus \
    -directory_name "svdb"  \
    -hierarchy_delimiter "/" \
    -run_name "{{ cell_name }}"
