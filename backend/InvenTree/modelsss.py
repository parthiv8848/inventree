import json

def extract_unique_models(input_file, output_file):
    # Load the data from the input JSON file
    with open(input_file, 'r') as infile:
        data = json.load(infile)
    
    # Create a set to store unique models
    unique_models = set()

    # Iterate through each item and collect unique models
    for item in data:
        model = item.get('model')
        if model:
            unique_models.add(model)

    # Convert the set to a list and save it to the output JSON file
    unique_models_list = list(unique_models)
    
    with open(output_file, 'w') as outfile:
        json.dump(unique_models_list, outfile, indent=4)

if __name__ == '__main__':
    input_file = 'data.json'  # Replace with your input file name
    output_file = 'unique_models.json'  # Replace with your desired output file name
    extract_unique_models(input_file, output_file)
    print(f"Unique models have been saved to {output_file}")
